import serial
import csv
import simplekml
import shutil
import os
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from ttkthemes import ThemedTk
import mysql.connector
from mysql.connector import Error
from mysql.connector import pooling
import time
import queue
import threading

# Serial port configuration
port = "COM5"  # Change this to your Arduino's serial port
baud_rate = 9600

# Initialize a queue for MySQL operations
mysql_queue = queue.Queue()

# MySQL database configuration
mysql_config = {
    'host': 'localhost',
    'port': 3306,
    'database': 'ok',
    'user': 'k',
    'password': 'nah'
}


def rename_old_table_and_create_new(connection):
    cursor = connection.cursor()
    epoch_time = str(int(time.time()))
    new_table_name = "sensor_data_" + epoch_time

    # Check if the old table exists and rename it
    cursor.execute("SHOW TABLES LIKE 'sensor_data'")
    result = cursor.fetchone()
    if result:
        rename_query = f"RENAME TABLE sensor_data TO {new_table_name}"
        cursor.execute(rename_query)
        print(f"Old table renamed to {new_table_name}")

    # Check if the new table name already exists to prevent duplicate table creation
    cursor.execute("SHOW TABLES LIKE 'sensor_data'")
    if not cursor.fetchone():
        # Create a new sensor_data table with the necessary schema if it does not exist
        create_table_query = """
        CREATE TABLE sensor_data (
            id INT AUTO_INCREMENT PRIMARY KEY,
            Time VARCHAR(255),
            Temperature DOUBLE,
            Pressure DOUBLE,
            Altitude DOUBLE,
            Latitude DOUBLE,
            Longitude DOUBLE,
            gps_altitude DOUBLE,
            gps_sats INT,
            gyro_x DOUBLE,
            gyro_y DOUBLE,
            gyro_z DOUBLE,
            bmp_status INT,
            gps_status INT,
            gyro_status INT,
            apc_status INT,
            servo_status INT,
            servo_rotation DOUBLE,
            sd_status INT
        )
        """
        cursor.execute(create_table_query)
        print("New sensor_data table created.")
    else:
        print("Table 'sensor_data' already exists, not creating a new table.")

    cursor.close()


def create_mysql_connection_pool(pool_name="mysql_pool", pool_size=5):
    pool = pooling.MySQLConnectionPool(pool_name=pool_name,
                                       pool_size=pool_size,
                                       pool_reset_session=True,
                                       **mysql_config)
    return pool

mysql_pool = create_mysql_connection_pool(pool_name="cansat_pool", pool_size=10)

def insert_data_to_mysql():
    print("MySQL insertion thread started.")
    while True:
        data = mysql_queue.get()
        if data is None:
            print("Exiting MySQL insertion thread.")
            break  # Exit loop if None is received

        try:
            print("Getting connection from pool...")
            connection = mysql_pool.get_connection()
            cursor = connection.cursor()
            print("Inserting data into MySQL...")
            insert_query = """
            INSERT INTO sensor_data (Time, Temperature, Pressure, Altitude, Latitude, Longitude, gps_altitude, gps_sats, gyro_x, gyro_y, gyro_z, bmp_status, gps_status, gyro_status, apc_status, servo_status, servo_rotation, sd_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, data)
            connection.commit()
            print("Data inserted successfully.")
        except Error as e:
            print(f"Error inserting data into MySQL database: {e}")
        finally:
            mysql_queue.task_done()
            if cursor:
                cursor.close()
            if connection:
                connection.close()  # Return the connection back to the pool


# Create the KML File with certain settings
def create_kml():
    kml = simplekml.Kml()
    linestring = kml.newlinestring(name="Vila2Sat_Track")
    linestring.style.linestyle.color = simplekml.Color.red
    linestring.style.linestyle.width = 4
    linestring.altitudemode = simplekml.AltitudeMode.absolute
    return kml, linestring

# Function that updates the kml
def update_kml(kml, linestring, coordinates, last_coordinate):
    linestring.coords = coordinates
    linestring.altitudemode = simplekml.AltitudeMode.absolute
    linestring.extrude = 0
    linestring.tessellate = 0

    lookat = simplekml.LookAt(longitude=last_coordinate[0],
                              latitude=last_coordinate[1],
                              altitude=last_coordinate[2] + 10,
                              heading=0,
                              tilt=45,
                              range=20,
                              altitudemode=simplekml.AltitudeMode.absolute)
    
    kml.document.lookat = lookat
    kml.save("live_track.kml")

def is_csv_empty(file_path):
    with open(file_path, 'r', newline='') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip header
        return not any(reader)  # Check if there's any data after the header

def load_existing_data(csv_file):
    coordinates = []
    if os.path.exists(csv_file) and not is_csv_empty(csv_file):
        with open(csv_file, 'r', newline='') as file:
            reader = csv.reader(file)
            next(reader)  # Skip header
            for row in reader:
                try:
                    lat, lon, alt = float(row[4]), float(row[5]), float(row[3])
                    coordinates.append((lon, lat, alt))
                except ValueError:
                    continue
    return coordinates

def create_backup_files(csv_file, kml_file):
    backup_folder = 'backup'
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_csv_file = os.path.join(backup_folder, f'{timestamp}_{csv_file}')
    backup_kml_file = os.path.join(backup_folder, f'{timestamp}_live_track.kml')

    if os.path.exists(csv_file):
        shutil.copy(csv_file, backup_csv_file)
    if os.path.exists("live_track.kml"):
        shutil.copy("live_track.kml", backup_kml_file)

    return backup_csv_file, backup_kml_file

def update_backup_files(backup_csv_file, backup_kml_file):
    shutil.copy("sheet.csv", backup_csv_file)
    shutil.copy("live_track.kml", backup_kml_file)

def parse_data(data_line):
    try:
        # Splitting the line at "=" and stripping extra spaces from key and value
        parts = data_line.split("=")
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip()
            return key, value
        else:
            return None, None
    except ValueError as e:
        print(f"Error parsing data_line '{data_line}': {e}")
        return None, None

def add_data_to_text_widget(text_widget, data):
    text_widget.config(state=tk.NORMAL)  # Temporarily enable the widget to modify it
    text_widget.insert(tk.END, data + '\n')  # Add data
    text_widget.see(tk.END)  # Scroll to the bottom
    text_widget.config(state=tk.DISABLED)  # Disable the widget again

def add_line_text_widget(text_widget):
    text_widget.config(state=tk.NORMAL)  # Temporarily enable the widget to modify it
    text_widget.insert(tk.END, '---------------\n')  # Add line
    text_widget.see(tk.END)  # Scroll to the bottom
    text_widget.config(state=tk.DISABLED)  # Disable the widget again

# CSV file configuration
csv_file = "sheet.csv"
csv_headers = ["Time", "Temperature", "Pressure", "Altitude", "Latitude", "Longitude", "gps_altitude", "gps_sats", "gyro_x", "gyro_y", "gyro_z", "bmp_status", "gps_status", "gyro_status", "apc_status", "servo_status", "servo_rotation", "sd_status"]

import time

def read_serial_data(text_widget, stop_event, ser, csv_file):
    sensor_values = {key: 'N/A' for key in csv_headers}  # Initialize all sensor values with 'N/A'
    new_data_received = False
    kml, linestring = create_kml()
    coordinates = load_existing_data(csv_file)
    backup_csv_file, backup_kml_file = create_backup_files(csv_file, "live_track.kml")

    def process_and_insert_data():
        nonlocal sensor_values
        # Write the current state of sensor_values to CSV
        with open(csv_file, 'a', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            row = [sensor_values.get(header, 'N/A') for header in csv_headers]
            csv_writer.writerow(row)
        print("CSV row written:", row)

        # Update backup files
        update_backup_files(backup_csv_file, backup_kml_file)
        print("Backup files updated.")

        # Insert data into MySQL
        data_for_mysql = tuple(sensor_values.get(header, 'N/A') for header in csv_headers)
        mysql_queue.put(data_for_mysql)
        print("Data enqueued for MySQL insertion.")

        # Update KML if latitude, longitude, and altitude are available
        if all(sensor_values[key] != 'N/A' for key in ['Latitude', 'Longitude', 'Altitude']):
            new_coords = (float(sensor_values['Longitude']), float(sensor_values['Latitude']), float(sensor_values['Altitude']))
            update_kml(kml, linestring, coordinates, new_coords)
            print("KML updated with new coordinates.")

    try:
        while not stop_event.is_set():
            if ser.in_waiting > 0:
                data_line = ser.readline().decode('utf-8').rstrip()
                add_data_to_text_widget(text_widget, data_line)

                key, value = parse_data(data_line)
                if key:
                    if key == 'Time' and new_data_received:  # Check if it's time for a new dataset
                        process_and_insert_data()  # Process the previous dataset
                        sensor_values = {k: 'N/A' for k in csv_headers}  # Reset for new data
                        new_data_received = False
                    sensor_values[key] = value  # Update sensor values dictionary with received data
                    new_data_received = True

    except serial.SerialException as e:
        add_data_to_text_widget(text_widget, f"Serial error: {e}\n")
    except Exception as e:
        add_data_to_text_widget(text_widget, f"Error: {e}\n")
    finally:
        if ser.is_open:
            ser.close()
        if new_data_received:
            process_and_insert_data()  # Ensure the last set of data is processed


# Global variable to keep track of whether the MySQL insertion thread has been started
mysql_thread_started = False
mysql_insertion_thread = None

# Function to handle stop reading
def stop_reading(stop_event):
    stop_event.set()  # Signal the thread to stop
    stop_mysql_thread()
    mysql_thread_started = False
    

def stop_mysql_thread():
    global mysql_insertion_thread  # This is to clearly indicate we're using the global variable
    if mysql_insertion_thread is not None:
        mysql_queue.put(None)  # Signal the thread to exit
        mysql_insertion_thread.join()
        mysql_insertion_thread = None  # Reset it so you can safely start it again if needed

# Function to handle start reading
def start_reading(text_widget, stop_event):
    global mysql_thread_started
    print("Starting to read...")

    try:
        # Start the MySQL insertion thread only if it hasn't been started already
        if not mysql_thread_started:
            print("Starting MySQL insertion thread...")
            mysql_insertion_thread = threading.Thread(target=insert_data_to_mysql, daemon=True)
            mysql_insertion_thread.start()
            mysql_thread_started = True
            print("MySQL insertion thread started.")

        # Connect to the database and prepare the table
        print("Connecting to database and preparing tables...")
        db_connection = mysql_pool.get_connection()
        rename_old_table_and_create_new(db_connection)
        db_connection.close()
        print("Database is ready for new data.")

        # Create CSV file with headers if it doesn't exist
        if not os.path.exists(csv_file):
            print("Creating CSV file...")
            with open(csv_file, 'w', newline='') as f:
                csv_writer = csv.writer(f)
                csv_writer.writerow(csv_headers)
            print("CSV file created.")

        # Create an initial KML file if it doesn't exist
        if not os.path.exists("live_track.kml"):
            print("Creating initial KML file...")
            kml, _ = create_kml()
            kml.save("live_track.kml")
            print("KML file created.")

        # Initialize the serial port
        print(f"Attempting to open serial port {port}...")
        ser = serial.Serial(port, baud_rate, timeout=1)
        print(f"Serial port {ser.name} opened successfully.")

        stop_event.clear()

        print("Starting serial data reading thread...")
        threading.Thread(target=read_serial_data, args=(text_widget, stop_event, ser, csv_file), daemon=True).start()
        print("Serial data reading thread started.")
    except serial.SerialException as e:
        add_data_to_text_widget(text_widget, f"Serial error: {e}")
        print(f"Serial error: {e}")
    except Error as e:
        add_data_to_text_widget(text_widget, f"Database error: {e}")
        print(f"Database error: {e}")
    except Exception as e:
        add_data_to_text_widget(text_widget, f"Error: {e}")
        print(f"Error: {e}")


# Function to reset CSV
def reset_csv(text_widget):
    try:
        if os.path.exists(csv_file):
            os.remove(csv_file)
        with open(csv_file, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(csv_headers)
        add_data_to_text_widget(text_widget, "CSV file has been reset.\n")
    except Exception as e:
        add_data_to_text_widget(text_widget, f"Error resetting CSV file: {e}\n")


# Tkinter UI setup

def setup_ui():
    root = ThemedTk(theme="Adapta")
    root.title("Vila2Sat Serial GUI")
    root.state('zoomed')

    style = ttk.Style(root)
    background_color = style.lookup('TFrame', 'background')  # Getting the default background color of the theme

    # Configuring button styles
    style.configure('TButton', font=('Helvetica', 12), background=background_color)
    style.configure('Green.TButton', foreground='green', background='green')
    style.configure('Red.TButton', foreground='red', background='red')

    # Adding a title label with the matching background
    title_label = ttk.Label(root, text="Vila2Sat Serial Monitor", font=('Helvetica', 16, 'bold'), background=background_color)
    title_label.pack(side=tk.TOP, pady=(10, 5), padx=10)

    top_frame = ttk.Frame(root)
    top_frame.pack(side=tk.TOP, fill=tk.X, pady=20)

    center_frame = ttk.Frame(top_frame)
    center_frame.pack(side=tk.TOP)

    # Styling the text widget to have a slightly rounded border
    text_widget = tk.Text(root, state=tk.DISABLED, bd=2, relief='groove', font=('Helvetica', 12))
    text_widget.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

    stop_event = threading.Event()

    start_button = ttk.Button(top_frame, text="Start Reading", style='Green.TButton', command=lambda: start_reading(text_widget, stop_event))
    start_button.pack(side=tk.LEFT, padx=5)

    stop_button = ttk.Button(top_frame, text="Stop Reading", style='Red.TButton', command=lambda: stop_reading(stop_event))
    stop_button.pack(side=tk.LEFT, padx=5)

    reset_button = ttk.Button(top_frame, text="Reset CSV", style='Red.TButton', command=lambda: reset_csv(text_widget))
    reset_button.pack(side=tk.RIGHT, padx=10)

    root.mainloop()

if __name__ == "__main__":
    setup_ui()
