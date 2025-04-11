from airflow import DAG
from airflow.providers.http.hooks.http import HttpHook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.decorators import task
from airflow.utils.dates import days_ago
from datetime import datetime
import json

# Coordinates for air pollution data
LATITUDE = '50.88'
LONGITUDE = '0.218'

# Airflow default args
default_args = {
    'owner': 'airflow',
    'start_date': days_ago(1),
}

# Connection IDs
POSTGRES_CONN_ID = 'postgres_default'
API_CONN_ID = 'openweathermap_org'  # Make sure this matches the actual Airflow connection ID

# Your OpenWeatherMap API key
API_KEY = '748ee12d2ac05695e3b4d0fae7821f03'  # Replace with your real key

# DAG definition
with DAG(
    dag_id='airpollution_etl_pipeline',
    default_args=default_args,
    schedule_interval='@daily',
    catchup=False,
    description='ETL pipeline to load air pollution data into PostgreSQL',
    tags=['etl', 'airpollution'],
) as dag:

    @task()
    def extract_airpollution_data():
        """Extract air pollution data from OpenWeather API"""
        http_hook = HttpHook(http_conn_id=API_CONN_ID, method='GET')
        endpoint = f'/data/2.5/air_pollution?lat={LATITUDE}&lon={LONGITUDE}&appid={API_KEY}'
        response = http_hook.run(endpoint)

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f'Failed to fetch air pollution data: {response.status_code}, {response.text}')

    @task()
    def transform_airpollution_data(data: dict):
        """Transform raw API data into structured format for DB insert"""
        entry = data['list'][0]
        components = entry['components']
        aqi = entry['main']['aqi']
        timestamp = datetime.utcfromtimestamp(entry['dt'])

        def get_aqi_description(aqi_level):
            return {
                1: "Good",
                2: "Fair",
                3: "Moderate",
                4: "Poor",
                5: "Very Poor"
            }.get(aqi_level, "Unknown")

        return {
            'latitude': float(LATITUDE),
            'longitude': float(LONGITUDE),
            'today_date': timestamp,
            'air_quality_index': aqi,
            'air_quality': get_aqi_description(aqi),
            'concentration_of_co': components.get('co'),
            'concentration_of_pm25': components.get('pm2_5'),
            'concentration_of_no2': components.get('no2'),
            'concentration_of_o3': components.get('o3'),
            'concentration_of_so2': components.get('so2'),
            'concentration_of_pm10': components.get('pm10'),
            'concentration_of_nh3': components.get('nh3')
        }

    @task()
    def load_to_postgres(record: dict):
        """Load transformed data into PostgreSQL"""
        hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        conn = hook.get_conn()
        cursor = conn.cursor()

        create_table_sql = """
            CREATE TABLE IF NOT EXISTS airpollution_data (
                latitude FLOAT,
                longitude FLOAT,
                today_date TIMESTAMP,
                air_quality_index INT,
                air_quality VARCHAR(50),
                concentration_of_co FLOAT,
                concentration_of_pm25 FLOAT,
                concentration_of_no2 FLOAT,
                concentration_of_o3 FLOAT,
                concentration_of_so2 FLOAT,
                concentration_of_pm10 FLOAT,
                concentration_of_nh3 FLOAT
            );
        """

        insert_sql = """
            INSERT INTO airpollution_data (
                latitude, longitude, today_date, air_quality_index, air_quality,
                concentration_of_co, concentration_of_pm25, concentration_of_no2,
                concentration_of_o3, concentration_of_so2, concentration_of_pm10, concentration_of_nh3
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """

        try:
            cursor.execute(create_table_sql)
            cursor.execute(insert_sql, (
                record['latitude'],
                record['longitude'],
                record['today_date'],
                record['air_quality_index'],
                record['air_quality'],
                record['concentration_of_co'],
                record['concentration_of_pm25'],
                record['concentration_of_no2'],
                record['concentration_of_o3'],
                record['concentration_of_so2'],
                record['concentration_of_pm10'],
                record['concentration_of_nh3']
            ))
            conn.commit()
        except Exception as e:
            print(f"Failed to insert data: {e}")
        finally:
            cursor.close()
            conn.close()

    # Task dependency order
    data = extract_airpollution_data()
    transformed = transform_airpollution_data(data)
    load_to_postgres(transformed)
