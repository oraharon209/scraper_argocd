import os
import subprocess
import time
from datetime import datetime, timedelta
import logging
import json
from kafka import KafkaConsumer, TopicPartition
from kubernetes import config
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO,  # filename='app.log', filemode='w',
                    format='%(name)s - %(levelname)s - %(message)s')


KAFKA_CONSUMER = os.getenv('KAFKA_CONSUMER', 'localhost')
KAFKA_PORT = os.getenv('KAFKA_PORT', '9092')
SASL_USER = os.getenv('SASL_USER', 'user1')
SASL_PASS = os.getenv('SASL_PASS', 'potato')
POD_NAMESPACE = os.getenv('POD_NAMESPACE', 'default')
MONGO_USER = os.getenv('MONGO_USER', 'root')
MONGO_PASS = os.getenv('MONGO_PASS', 'potato')
MONGO_HOST = os.getenv('MONGO_HOST', 'mongo1')
MONGO_PORT = os.getenv('MONGO_PORT', 27017)
REPO_URL = os.getenv('REPO_URL',
                     "https://github.com/oraharon209/argotest/tree/main/charts")
DAILY_CHART = os.getenv('DAILY_CHART', 'daily_job.tgz')
LIVE_CHART = os.getenv('LIVE_CHART', 'live_job.tgz')
TOPIC_NAME = f"{POD_NAMESPACE}_euro2024_matches"
TOPIC_FAV_TEAM = f"{POD_NAMESPACE}_fav_team"


def write_to_db(kafka_message):
    """Write the Kafka message to today's MongoDB collection."""
    # Use the MongoDB instance running on port 27017
    conn_str = f'mongodb://{MONGO_USER}:{MONGO_PASS}@{MONGO_HOST}:{MONGO_PORT}/'
    mongo_client = MongoClient(conn_str,
                               serverSelectionTimeoutMS=5000,
                               authSource='admin',
                               authMechanism='SCRAM-SHA-1')
    db = mongo_client[TOPIC_NAME]
    collection_today = db[datetime.now().strftime('%Y-%m-%d')]
    try:
        for game_key, game_data in kafka_message.items():
            game_data["_id"] = game_key  # Use the game key as the document ID
            collection_today.insert_one(game_data)
            logging.info(f"Inserted Kafka message into MongoDB: {game_data}")
    except Exception as e:
        logging.error(f"Failed to write to MongoDB: {str(e)}")


def run_command(command):
    """Run a shell command and return its output."""
    try:
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info(f"Command output: {result.stdout.decode('utf-8').strip()}")
        return result.stdout.decode('utf-8').strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Command '{command}' failed with return code {e.returncode}")
        logging.error(f"Error output: {e.stderr.decode('utf-8').strip()}")


def start_kubernetes_job(job_name, chart_path, fav_team):
    """Deploy or upgrade the application using Helm from a local chart path."""
    try:
        config.load_kube_config()
        release_name = f"{POD_NAMESPACE}-{job_name}"

        # Set up environment variables for the job
        fav_team_value = fav_team or ""

        # Deploy or upgrade the application
        command = (f"helm upgrade --install {release_name} {REPO_URL}{chart_path} "
                   f"--namespace {POD_NAMESPACE} "
                   f"--set releaseOverride={release_name} "  # Set the release name explicitly
                   f"--set-string envs.FAV_TEAM={fav_team_value}")
        run_command(command)
        logging.info(f"Job {release_name} deployed in namespace \
        '{POD_NAMESPACE}' from chart path '{chart_path}'.")
    except Exception as e:
        logging.error(f"Error creating Kubernetes Job: {str(e)}")


def create_consumer(offset):
    while True:
        try:
            consumer = KafkaConsumer(
                bootstrap_servers=f'{KAFKA_CONSUMER}:{KAFKA_PORT}',
                security_protocol="SASL_PLAINTEXT",
                sasl_mechanism="SCRAM-SHA-256",
                sasl_plain_username=SASL_USER,
                sasl_plain_password=SASL_PASS,
                auto_offset_reset=offset,  # 'earliest',
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode('utf-8'))
            )
            break
        except Exception as e:
            logging.error(f"Failed to connect to Kafka: {str(e)}")
            logging.info("Retrying in 5 seconds...")
            time.sleep(5)
    return consumer


def get_last_fav_team():
    offset = 'latest'
    consumer = None
    try:
        consumer = create_consumer(offset)

        tp = TopicPartition(TOPIC_FAV_TEAM, 0)
        consumer.assign([tp])
        consumer.seek_to_end(tp)
        last_offset = consumer.position(tp)

        if last_offset == 0:
            logging.info(f"No messages found in topic {TOPIC_FAV_TEAM}.")
            return None

        consumer.seek(tp, last_offset - 1)
        message = next(consumer)
        fav_team = message.value.get('fav_team')
        logging.info(f"Retrieved fav_team from topic {TOPIC_FAV_TEAM}: {fav_team}")
        return fav_team
    except Exception as e:
        logging.error(f"Error retrieving fav_team from topic {TOPIC_FAV_TEAM}: {str(e)}")
        return None
    finally:
        consumer.close()


def check_kafka_topic():
    main_offset = 'earliest'
    first_run = True
    written_to_db = False
    kafka_games_value = None
    while True:
        current_time = datetime.now().strftime('%H:%M')
        logging.debug(f"first run: {first_run}")
        logging.debug(f"current time: {current_time}")
        logging.debug(f"time check: {current_time == '0:0'}")
        if first_run or current_time == "0:0":
            first_run = False
            consumer = create_consumer(main_offset)
            kafka_games_value = check_daily(consumer)
            logging.info(f"kafka message: {kafka_games_value}")
            if kafka_games_value and not written_to_db:
                write_to_db(kafka_games_value)
                written_to_db = True
        if kafka_games_value:
            logging.info(f"kafka message: {kafka_games_value}")
            check_live_data(kafka_games_value)
        time.sleep(30)


def check_live_data(messages):
    for game_key, game_data in messages.items():
        current_time = datetime.now().strftime('%H:%M')
        logging.info(f"game_data: {game_data}")
        logging.info(f"game_key: {game_key}")
        game_time_str = game_data.get('time')
        logging.info(f"game_time: {game_time_str}")

        if game_time_str:
            game_time = datetime.strptime(game_time_str, '%H:%M')
            current_time = datetime.strptime(current_time, '%H:%M')
            logging.info(f"current time: {current_time}, game_time: {game_time}")
            if current_time == (game_time - timedelta(minutes=2)):
                # check if a container already started for this game
                start_job_request('live', LIVE_CHART)
                break


def check_daily(consumer):
    current_date = datetime.now().strftime('%Y-%m-%d')
    try:
        partitions = consumer.partitions_for_topic(TOPIC_NAME)
        if partitions is None:
            logging.info(f"Topic {TOPIC_NAME} does not exist. Starting container...")
            start_job_request('daily', DAILY_CHART)
        else:
            tp = TopicPartition(TOPIC_NAME, 0)
            consumer.assign([tp])
            consumer.seek_to_end(tp)
            last_offset = consumer.position(tp)
            if last_offset == 0:
                logging.info(f"No game data in topic {TOPIC_NAME}. Starting container...")
                start_job_request('daily', DAILY_CHART)
            else:
                consumer.seek(tp, last_offset - 1)
                message = next(consumer)
                logging.debug(f"message: {message}")
                message_date = message.key.decode('utf-8')
                logging.info(f"message_date: {message_date}")
                if message_date != current_date:
                    logging.info(f"Latest message date ({message_date}) is not today's date. Starting container...")
                    start_job_request('daily', DAILY_CHART)
                else:
                    logging.info(
                        f"Game data for today ({current_date}) found in topic {TOPIC_NAME}. "
                        f"No need to start container.")
                    # Check if the current time matches any game time

                    logging.debug(f"message value: {message.value}")
                    return message.value

    except Exception as e:
        logging.error(f"Error checking Kafka topic: {str(e)}")
    finally:
        if consumer:
            consumer.close()


def start_job_request(j_name, job_image):
    fav_team = get_last_fav_team()
    start_kubernetes_job(j_name, job_image, fav_team)


if __name__ == '__main__':
    check_kafka_topic()
