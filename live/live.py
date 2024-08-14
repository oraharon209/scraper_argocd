import logging
import time
import json
import re
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as expct_cond
from bs4 import BeautifulSoup
from kafka import KafkaProducer
from discord_webhook import DiscordWebhook, DiscordEmbed


# Configure logging
logging.basicConfig(level=logging.INFO,  # filename='app.log', filemode='w',
                    format='%(name)s - %(levelname)s - %(message)s')


KAFKA_PRODUCERS = os.getenv('KAFKA_PRODUCERS', 'localhost').split(",")
SASL_USER = os.getenv('SASL_USER', 'user1')
SASL_PASS = os.getenv('SASL_PASS', 'potato')
POD_NAMESPACE = os.getenv('POD_NAMESPACE', 'default')
TOPIC_NAME = f"{POD_NAMESPACE}_euro2024_matches_live"
FAV_TEAM = os.getenv('FAV_TEAM', 'Spain')
DISCORD_URL = os.getenv('DISCORD_URL', "https://discord.com/api/webhooks/1252882210101526539/"
                                       "FZGB42Xd0SCqmzd_OkvIxBR7UKRpzVlW7Ysk7bEi6dE8GmfilK9dF5-VdblpyNSxMd6v")


def create_producer():
    while True:
        try:
            k_producer = KafkaProducer(
                bootstrap_servers=KAFKA_PRODUCERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                security_protocol="SASL_PLAINTEXT",
                sasl_mechanism="SCRAM-SHA-256",
                sasl_plain_username=SASL_USER,
                sasl_plain_password=SASL_PASS,
                retries=5,  # Retry up to 5 times in case of failure
                batch_size=16384,  # 16 KB batch size
                linger_ms=100,  # Send messages immediately
                compression_type='gzip'  # Enable gzip compression
                )
            break
        except Exception as err:
            logging.error(f"Failed to connect to Kafka: {err}")
            logging.info("Retrying in 5 seconds...")
            time.sleep(5)
    return k_producer


# Function to send message to Kafka
def send_kafka_message(k_producer, msg):
    try:
        k_producer.send(TOPIC_NAME, value=msg)
        logging.info(f"Sent message: {msg}")
    except Exception as err:
        logging.error(f"Failed to send message: {err}")


def send_discord_message(message):
    # Your Discord webhook URL
    webhook_url = DISCORD_URL
    # Create a webhook
    webhook = DiscordWebhook(url=webhook_url)
    # Create an embed for the message
    embed = DiscordEmbed(title='Match Update', description=message, color=242424)
    # Add the embed to the webhook
    webhook.add_embed(embed)
    # Send the webhook
    webhook.execute()
    logging.info("Discord message sent")


def scrape_upcoming(c_driver, game_state='LIVE', timeout=5 * 60, check_interval=10):
    t_end = time.time() + timeout
    today_date = datetime.now().strftime('%Y-%m-%d')
    while time.time() < t_end:
        # Wait for the matches-calendar-tab element to be present
        try:
            logging.info(f"Waiting for element with date: {today_date}")
            element = WebDriverWait(c_driver, 20).until(
                expct_cond.presence_of_element_located(
                    (By.CSS_SELECTOR, f'div.matches-calendar-tab[data-tab-id="{today_date}"]'))
            )
            logging.debug(f"Element {element} found")
        except Exception as err:
            logging.error(f"Error: {err}")
            break
        # Wait for additional time (e.g., 2 seconds) to ensure the page has fully loaded
        time.sleep(2)

        logging.info("Scraped UEFA website for upcoming games")

        soup = BeautifulSoup(c_driver.page_source, 'html.parser')
        matches_calendar = soup.find('div', class_='matches-calendar-tab',
                                     attrs={'data-tab-id': today_date})
        logging.debug(f'matches calendar: {matches_calendar}')
        if not matches_calendar:
            logging.error("no matches today, why am i alive, just to suffer...")
            break

        if any(matches_calendar.find_all('a', class_='mu', attrs={'data-status': game_state})):
            break
        else:
            logging.info("waiting to scrape upcoming again")
            c_driver.refresh()
            time.sleep(check_interval)
            continue


def scrape_euro_matches(c_driver, target_status, euro_url, kafka_producer, today_date):
    # Kafka producer configuration
    live_games_data = {}
    c_driver.get(euro_url)
    # first loop: loop until at least one game is live
    scrape_upcoming(c_driver, target_status)
    # second loop: loop until all live games have ended.
    while True:
        # Wait for the matches-calendar-tab element to be present
        try:
            logging.info(f"Waiting for element with date: {today_date}")
            element = WebDriverWait(c_driver, 20).until(
                expct_cond.presence_of_element_located(
                    (By.CSS_SELECTOR, f'div.matches-calendar-tab[data-tab-id="{today_date}"]'))
            )
            logging.debug(f"Element {element} found")
        except Exception as err:
            logging.error(f"Error: {err}")
            break
        # Wait for additional time (e.g., 2 seconds) to ensure the page has fully loaded
        time.sleep(2)
        logging.info("scraped UEFA website")
        soup = BeautifulSoup(c_driver.page_source, 'html.parser')
        matches_calendar = soup.find('div', class_='matches-calendar-tab',
                                     attrs={'data-tab-id': datetime.now().strftime('%Y-%m-%d')})
        logging.debug(f'matches calendar: {matches_calendar}')
        if not matches_calendar:
            logging.info(f"no games schedules for today")
            break
        # find all live games in the list
        live_games = matches_calendar.find_all('a', class_='mu', attrs={'data-status': target_status})
        logging.debug(f"live games: {live_games}")
        for game in live_games:
            logging.debug(f'game data: {game}')
            # Extract match details from the JSON data embedded in the script tag
            script_tag = game.find('script', type='application/ld+json')
            if script_tag:
                game_data = json.loads(script_tag.string)
                game_name = game_data['name']
                logging.debug(f'game name: {game_name}')
                home_team = game_data['homeTeam']['name']
                away_team = game_data['awayTeam']['name']
                logging.debug(f"home team name: {home_team}")
                logging.debug(f"away team name: {away_team}")
                # Extract scores
                score_pattern = re.compile(r'(\d+)-(\d+)')
                score_match = score_pattern.search(game_name)
                if score_match:
                    home_score = int(score_match.group(1))
                    away_score = int(score_match.group(2))
                else:
                    home_score = 0  # Default value
                    away_score = 0  # Default value

                logging.info(f"current game data: {live_games_data}")
                logging.info(f"game status: {game['data-status']}")
                game_id = f"{home_team} vs {away_team}"
                # first check to see if game just started
                if game_id not in live_games_data:
                    live_games_data[game_id] = {
                        'home_team': home_team,
                        'away_team': away_team,
                        'home_score': home_score,
                        'away_score': away_score,
                        'date': current_date
                    }
                    send_kafka_message(kafka_producer, live_games_data)
                    if FAV_TEAM in game_id and game['data-status'] == target_status:
                        send_discord_message(f"match {live_games_data[game_id]['home_team']} vs "
                                             f"{live_games_data[game_id]['away_team']} has started!")

                # if score has changed since last score update
                if (live_games_data[game_id]['home_score'] != home_score
                    or live_games_data[game_id]['away_score'] != away_score):
                    match_message = (f"Score changed for match {live_games_data[game_id]['home_team']} vs "
                                     f"{live_games_data[game_id]['away_team']} : "
                                     f"{live_games_data[game_id]['home_team']} {home_score} - {away_score} "
                                     f"{live_games_data[game_id]['away_team']}")
                    logging.info(f"match message: {match_message}")
                    if FAV_TEAM in game_id and game['data-status'] == target_status:
                        send_discord_message(match_message)
                    logging.info(f"live_games_data: {live_games_data}")
                    send_kafka_message(kafka_producer, live_games_data)

                # Store current game data in the dictionary
                live_games_data[game_id] = {
                    'home_team': home_team,
                    'away_team': away_team,
                    'home_score': home_score,
                    'away_score': away_score,
                    'date': current_date
                }
                logging.info(f"current game data: {live_games_data}")

        if any(game['data-status'] == target_status for game in live_games):
            logging.info("There are still ongoing LIVE games")
            c_driver.refresh()
            time.sleep(10)
        else:
            break

    logging.info("WebDriver quit")


if __name__ == "__main__":
    current_date = datetime.now().strftime('%Y-%m-%d')
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # URL of the Euro 2024 fixtures and results page
    url = f"https://www.uefa.com/euro2024/fixtures-results/#/d/{current_date}"
    # Kafka producer
    producer = create_producer()
    # Initialize the Chrome WebDriver
    try:
        with webdriver.Chrome(options=options) as driver:
            scrape_euro_matches(driver, 'LIVE', url, producer, current_date)
    except Exception as e:
        logging.error(f"Error initializing ChromeDriver: {e}")
        exit(-1)
    finally:
        producer.flush()
        producer.close()
