import logging
import time
import json
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as expct_cond
from bs4 import BeautifulSoup
from kafka import KafkaProducer


# Configure logging
logging.basicConfig(level=logging.INFO,  # filename='app.log', filemode='w',
                    format='%(name)s - %(levelname)s - %(message)s')

# Kafka configuration
KAFKA_PRODUCERS = os.getenv('KAFKA_PRODUCERS', 'localhost').split(',')
SASL_USER = os.getenv('SASL_USER', 'user1')
SASL_PASS = os.getenv('SASL_PASS', 'potato')
POD_NAMESPACE = os.getenv('POD_NAMESPACE', 'default')
TOPIC_NAME = f"{POD_NAMESPACE}_euro2024_matches"
FAV_TEAM = os.getenv('FAV_TEAM', 'Scotland')


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
def send_kafka_message(k_producer, date_key, msg):
    try:
        k_producer.send(TOPIC_NAME, key=date_key.encode(), value=msg)
        logging.info(f"Sent message: {msg}")
    except Exception as err:
        logging.error(f"Failed to send message: {err}")


def scrape_euro_2024_matches(c_driver, euro_url, kafka_producer, today_date):
    logging.info(f"url: {euro_url}")
    today_games_data = {}
    # Load the webpage
    try:
        logging.debug(f"Loading URL: {euro_url}")
        c_driver.get(euro_url)
        logging.info("URL loaded successfully")
    except Exception as err:
        logging.error(f"Error loading URL: {err}")
        return today_games_data

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
        c_driver.quit()
        return today_games_data

    # Wait for additional time (e.g., 2 seconds) to ensure the page has fully loaded
    time.sleep(2)

    # Parse the page source with BeautifulSoup
    soup = BeautifulSoup(c_driver.page_source, 'html.parser')
    c_driver.quit()

    # Find the div with the class 'matches-calendar-tab' and the data-tab-id attribute equal to the current date
    matches_calendar = soup.find('div', class_='matches-calendar-tab',
                                 attrs={'data-tab-id': today_date})
    logging.debug(f'matches calendar: {matches_calendar}')
    if not matches_calendar:
        logging.error("no matches today, why am i alive, just to suffer...")
        return today_games_data

    # Find all match elements within this div
    today_games = matches_calendar.find_all('a', class_='mu')
    if not today_games:
        logging.error("No matches found for today.")
        return today_games_data
    logging.debug(f"today games: {today_games}")
    for game in today_games:
        logging.debug(f'game data: {game}')
        # Extract match details from the JSON data embedded in the script tag
        script_tag = game.find('script', type='application/ld+json')
        if script_tag:
            game_data = json.loads(script_tag.string)
            game_name = game_data['name']
            logging.debug(f'game name: {game_name}')
            home_team_name = game_data['homeTeam']['name']
            away_team_name = game_data['awayTeam']['name']
            logging.debug(f"home team name: {home_team_name}")
            logging.debug(f"away team name: {away_team_name}")

            # Store current game data in the dictionary
            match_time = datetime.strptime(game_data['startDate'], '%Y-%m-%dT%H:%M:%S.%fZ').strftime('%H:%M')
            today_games_data[game_name] = {
                'home_team': home_team_name,
                'away_team': away_team_name,
                'time': match_time
            }

    logging.info(f"today games data: {today_games_data}")
    send_kafka_message(kafka_producer, today_date, today_games_data)


if __name__ == "__main__":
    current_date = datetime.now().strftime('%Y-%m-%d')
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # URL of the Euro 2024 fixtures and results page
    url = f'https://www.uefa.com/euro2024/fixtures-results/#/d/{current_date}'
    # Kafka producer
    producer = create_producer()
    # Initialize the Chrome WebDriver
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        logging.error(f"Error initializing ChromeDriver: {e}")
        exit(-1)
    try:
        # Trigger the scraping and send the output to Kafka
        scrape_euro_2024_matches(driver, url, producer, current_date)
    except Exception as e:
        driver.quit()
        logging.error(f"Error initializing ChromeDriver: {e}")
    finally:
        producer.flush()
        producer.close()
