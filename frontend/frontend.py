import os
import json
import threading
import time
import logging
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template
from kafka import KafkaConsumer, KafkaProducer


logging.basicConfig(level=logging.INFO,  # filename='app.log', filemode='w',
                    format='%(name)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Kafka configuration
KAFKA_CONSUMER = os.getenv('KAFKA_CONSUMER', 'localhost')
KAFKA_PRODUCERS = os.getenv('KAFKA_PRODUCERS', 'localhost').split(',')
KAFKA_PORT = os.getenv('KAFKA_PORT', '9092')
SASL_USER = os.getenv('SASL_USER', 'user1')
SASL_PASS = os.getenv('SASL_PASS', 'potato')
POD_NAMESPACE = os.getenv('POD_NAMESPACE', 'default')
TOPIC_NAME = f"{POD_NAMESPACE}_euro2024_matches"
TOPIC_NAME_LIVE = f"{POD_NAMESPACE}_euro2024_matches_live"
TOPIC_FAV_TEAM = f"{POD_NAMESPACE}_fav_team"
euro_2024_teams = [
    "Austria", "Belgium", "Denmark", "England", "France", "Georgia", "Germany", "Italy",
    "Netherlands", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Switzerland",
    "Türkiye", "Albania", "Croatia", "Czechia", "Hungary", "Poland", "Scotland", "Serbia",
    "Ukraine", "Greece", "Iceland", "Wales", "Bosnia and Herzegovina", "Estonia", "Finland",
    "Israel", "Kazakhstan", "Luxembourg", "Andorra", "Armenia", "Azerbaijan", "Belarus",
    "Bulgaria", "Cyprus", "Faroe Islands", "Gibraltar", "Kosovo", "Latvia", "Liechtenstein",
    "Lithuania", "Malta", "Moldova", "Montenegro", "North Macedonia", "Northern Ireland",
    "Norway", "Republic of Ireland", "San Marino", "Sweden"
]
# Shared list to store consumed messages
messages = []
live_messages = {}


def create_consumer(topic_name):
    while True:
        try:
            logging.info(f"SASL_USER: {SASL_USER}, SASL_PASS: {SASL_PASS}")
            consumer = KafkaConsumer(
                topic_name,
                bootstrap_servers=f'{KAFKA_CONSUMER}:{KAFKA_PORT}',
                security_protocol="SASL_PLAINTEXT",
                sasl_mechanism="SCRAM-SHA-256",
                sasl_plain_username=SASL_USER,
                sasl_plain_password=SASL_PASS,
                auto_offset_reset='earliest',  # Start reading at the earliest available offset
                enable_auto_commit=True,  # Enable automatic offset commit
                value_deserializer=lambda m: json.loads(m.decode('utf-8'))
            )
            break
        except Exception as e:
            logging.error(f"Failed to connect to Kafka: {str(e)}")
            logging.info("Retrying in 5 seconds...")
            time.sleep(5)

    return consumer


def create_producer():
    while True:
        try:
            logging.info(f"SASL_USER: {SASL_USER}, SASL_PASS: {SASL_PASS}")
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


def consume_messages():
    consumer = create_consumer(TOPIC_NAME)
    try:
        for message in consumer:
            msg = message.value
            logging.info(f"Received message: {msg}")
            try:
                today_date_str = datetime.today().strftime('%Y-%m-%d')

                if message.key.decode('utf-8') != today_date_str:
                    continue

                for game_key, game_data in msg.items():
                    home_team = game_data['home_team']
                    away_team = game_data['away_team']
                    game_time = game_data['time']
                    extracted_message = {
                        'home_team': home_team,
                        'away_team': away_team,
                        'time': game_time
                    }
                    messages.append(extracted_message)
                    logging.info(f"Processed message: {extracted_message}")

            except KeyError as e:
                logging.error(f"Key error: {str(e)}")
            except json.JSONDecodeError as e:
                logging.error(f"JSON decode error: {str(e)}")
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


def consume_messages_live():
    consumer = create_consumer(TOPIC_NAME_LIVE)
    try:
        for message in consumer:
            msg = message.value
            logging.info(f"live msg: {msg}")
            try:
                # Parse the message based on the new structure
                for game_name, game_data in msg.items():
                    if game_data['date'] != datetime.now().strftime('%Y-%m-%d'):
                        continue
                    home_team = game_data['home_team']
                    away_team = game_data['away_team']
                    home_score = game_data['home_score']
                    away_score = game_data['away_score']
                    logging.info(f"game name is: {game_name}")
                    game_id = f"{home_team} vs {away_team}"
                    logging.info(f"game id is : {game_id}")
                    extracted_message = {
                        'home_team': home_team,
                        'away_team': away_team,
                        'home_score': home_score,
                        'away_score': away_score
                    }
                    if game_id in live_messages:
                        live_messages[game_id].update(extracted_message)
                        logging.info(f"Updated message for match {game_id}: {extracted_message}")
                    else:
                        live_messages[game_id] = extracted_message
                        logging.info(f"Received new message for match {game_id}: {extracted_message}")
                logging.info(f"live messages at loop end: {live_messages}")
            except KeyError as e:
                logging.error(f"Key error: {str(e)}")
            except json.JSONDecodeError as e:
                logging.error(f"JSON decode error: {str(e)}")
    except KeyboardInterrupt:
        pass
    finally:
        logging.info(f"live messages at loop end: {live_messages}")
        consumer.close()


# Route to display the messages
@app.route('/')
def index():
    return render_template('index.html',
                           teams=euro_2024_teams,
                           messages=messages,
                           live_messages=live_messages.values())


@app.route('/fav_team', methods=['POST'])
def fav_team():
    team = request.form['team']
    producer = create_producer()
    producer.send(TOPIC_FAV_TEAM, {'fav_team': team})
    logging.info(f"sent message {{'fav_team': {team}}} to topic {TOPIC_FAV_TEAM}")
    producer.flush()
    producer.close()
    return redirect(url_for('index'))


if __name__ == '__main__':
    # Start Kafka consumer in a separate thread
    consumer_thread = threading.Thread(target=consume_messages)
    consumer_thread.start()

    live_consumer_thread = threading.Thread(target=consume_messages_live)
    live_consumer_thread.start()

    app.run(host='0.0.0.0', port=5000)
