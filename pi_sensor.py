import time
import board
import adafruit_lsm6ds.lsm6ds33
import adafruit_lis3mdl
import adafruit_lps25
import math
import requests
import json
from ahrs.filters import Madgwick
import numpy as np

# Server configuration
SERVER_URL = "http://localhost:8000"  # Change this to your game server's IP

# Initialize I2C
i2c = board.I2C()

# Initialize sensors
try:
    # LSM6DS33 - Accelerometer and Gyroscope
    lsm6ds = adafruit_lsm6ds.lsm6ds33.LSM6DS33(i2c)
    # LIS3MDL - Magnetometer
    lis3mdl = adafruit_lis3mdl.LIS3MDL(i2c)
    # LPS25 - Barometer (optional, for future altitude tracking)
    lps25 = adafruit_lps25.LPS25(i2c)
    
    print("All sensors initialized successfully")
except Exception as e:
    print(f"Error initializing sensors: {e}")
    raise

# Initialize Madgwick filter for sensor fusion
# 100 Hz sample rate
madgwick = Madgwick(freq=100)
q = np.array([1.0, 0.0, 0.0, 0.0])  # Initial quaternion

def get_sensor_data():
    try:
        # Get acceleration data (in m/s^2)
        accel_x, accel_y, accel_z = lsm6ds.acceleration
        
        # Get gyroscope data (in rad/s)
        gyro_x, gyro_y, gyro_z = [math.radians(x) for x in lsm6ds.gyro]
        
        # Get magnetometer data (in uT)
        mag_x, mag_y, mag_z = lis3mdl.magnetic
        
        # Optional: Get pressure (in hPa) and temperature (in °C)
        pressure = lps25.pressure
        temperature = lps25.temperature
        
        return {
            'accel': (accel_x, accel_y, accel_z),
            'gyro': (gyro_x, gyro_y, gyro_z),
            'mag': (mag_x, mag_y, mag_z),
            'pressure': pressure,
            'temperature': temperature
        }
    except Exception as e:
        print(f"Error reading sensor data: {e}")
        return None

def update_orientation(accel, gyro, mag):
    global q
    # Update orientation estimate using Madgwick filter
    q = madgwick.update(q, gyro, accel, mag)
    
    # Convert quaternion to Euler angles
    roll = math.atan2(2 * (q[0] * q[1] + q[2] * q[3]), 1 - 2 * (q[1]**2 + q[2]**2))
    pitch = math.asin(2 * (q[0] * q[2] - q[3] * q[1]))
    yaw = math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2]**2 + q[3]**2))
    
    # Convert to degrees
    roll_deg = math.degrees(roll)
    pitch_deg = math.degrees(pitch)
    yaw_deg = math.degrees(yaw)
    
    return roll_deg, pitch_deg, yaw_deg

print("Starting sensor reading loop...")

try:
    while True:
        # Get sensor data
        sensor_data = get_sensor_data()
        if sensor_data is None:
            time.sleep(0.01)
            continue
            
        # Update orientation
        roll, pitch, yaw = update_orientation(
            sensor_data['accel'],
            sensor_data['gyro'],
            sensor_data['mag']
        )
        
        # Convert acceleration to g-force (1g = 9.81 m/s^2)
        ax = sensor_data['accel'][0] / 9.81
        ay = sensor_data['accel'][1] / 9.81
        az = sensor_data['accel'][2] / 9.81
        
        # Prepare data in the format expected by the game
        game_data = {
            "o_alpha": yaw,      # Map to yaw (Z-axis rotation)
            "o_beta": pitch,     # Map to pitch (X-axis rotation)
            "o_gamma": roll,     # Map to roll (Y-axis rotation)
            "ax": ax,           # Accelerometer X in g-force
            "ay": ay,           # Accelerometer Y in g-force
            "az": az,           # Accelerometer Z in g-force
            # Additional data available but not used by game currently
            "pressure": sensor_data['pressure'],
            "temperature": sensor_data['temperature']
        }
        
        # Send data to server
        try:
            response = requests.post(
                f"{SERVER_URL}/sensor_data",
                json=game_data,
                headers={'Content-Type': 'application/json'}
            )
            if response.status_code != 200:
                print(f"Error sending data: {response.status_code}")
        except Exception as e:
            print(f"Connection error: {e}")
        
        # Print values for debugging
        print(f"Roll: {roll:.2f}° Pitch: {pitch:.2f}° Yaw: {yaw:.2f}°")
        print(f"Accel: X={ax:.2f}g Y={ay:.2f}g Z={az:.2f}g")
        print(f"Pressure: {sensor_data['pressure']:.1f}hPa, Temp: {sensor_data['temperature']:.1f}°C")
        
        time.sleep(0.01)  # 100Hz update rate

except KeyboardInterrupt:
    print("\nProgram stopped by user")
except Exception as e:
    print(f"Error: {e}")
finally:
    print("Cleaning up...") 