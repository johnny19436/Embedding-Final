import numpy as np
from ahrs.filters import Madgwick
import smbus2 as smbus
import time
import struct
import requests
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from queue import Queue
from threading import Thread, Event

# ICM20948 Registers
ICM20948_ADDR = 0x68
REG_BANK_SEL = 0x7F

# Bank 0
B0_WHO_AM_I = 0x00
B0_USER_CTRL = 0x03
B0_LP_CONFIG = 0x05
B0_PWR_MGMT_1 = 0x06
B0_PWR_MGMT_2 = 0x07
B0_INT_PIN_CFG = 0x0F
B0_INT_ENABLE = 0x10
B0_INT_ENABLE_1 = 0x11
B0_I2C_MST_STATUS = 0x17
B0_ACCEL_XOUT_H = 0x2D
B0_GYRO_XOUT_H = 0x33

# Bank 2
B2_GYRO_SMPLRT_DIV = 0x00
B2_GYRO_CONFIG_1 = 0x01
B2_ACCEL_SMPLRT_DIV = 0x10
B2_ACCEL_CONFIG = 0x14

# Bank 3
B3_I2C_MST_CTRL = 0x01
B3_I2C_SLV0_ADDR = 0x03
B3_I2C_SLV0_REG = 0x04
B3_I2C_SLV0_CTRL = 0x05
B3_I2C_SLV0_DO = 0x06

# Magnetometer (AK09916)
MAG_ADDR = 0x0C
MAG_WHO_AM_I = 0x01
MAG_HXL = 0x11
MAG_CNTL2 = 0x31
MAG_CNTL3 = 0x32

# Initialize Madgwick filter
fuse = Madgwick(sampleperiod=0.01, beta=0.1)  # Increased beta for faster convergence
q = np.array([1., 0., 0., 0.])  # Initial quaternion
last_update = time.time()

# Server configuration
session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=0.1)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)
SERVER_URL = "http://172.18.108.80:8000"

class ICM20948:
    def __init__(self, bus):
        self.bus = bus
        self.gyro_scale = 131.0  # For ±250 dps
        self.accel_scale = 16384.0  # For ±2g
        self.mag_scale = 0.15  # µT per LSB
        
        # Calibration offsets
        self.gyro_offset = np.zeros(3)
        self.accel_offset = np.zeros(3)
        self.mag_offset = np.zeros(3)
        self.calibration_samples = 100

    def write_byte(self, reg, val):
        return self.bus.write_byte_data(ICM20948_ADDR, reg, val)

    def read_byte(self, reg):
        return self.bus.read_byte_data(ICM20948_ADDR, reg)

    def read_bytes(self, reg, length):
        return self.bus.read_i2c_block_data(ICM20948_ADDR, reg, length)

    def select_bank(self, bank):
        self.write_byte(REG_BANK_SEL, bank << 4)

    def initialize(self):
        # Check device ID
        self.select_bank(0)
        device_id = self.read_byte(B0_WHO_AM_I)
        if device_id != 0xEA:
            raise RuntimeError(f"Unexpected device ID: {hex(device_id)}")
        print(f"ICM20948 Device ID: {hex(device_id)}")

        # Reset device
        self.select_bank(0)
        self.write_byte(B0_PWR_MGMT_1, 0x80)
        time.sleep(0.1)

        # Wake up
        self.write_byte(B0_PWR_MGMT_1, 0x01)
        time.sleep(0.1)

        # Configure power management
        self.write_byte(B0_PWR_MGMT_2, 0x00)
        time.sleep(0.1)

        # Configure gyro and accelerometer
        self.select_bank(2)
        self.write_byte(B2_GYRO_SMPLRT_DIV, 0x07)
        self.write_byte(B2_GYRO_CONFIG_1, 0x01)
        self.write_byte(B2_ACCEL_SMPLRT_DIV, 0x07)
        self.write_byte(B2_ACCEL_CONFIG, 0x01)

        # Configure I2C master
        self.select_bank(0)
        self.write_byte(B0_USER_CTRL, 0x00)    # Disable I2C master
        time.sleep(0.1)
        self.write_byte(B0_INT_PIN_CFG, 0x02)  # Enable bypass
        time.sleep(0.1)

        # Initialize magnetometer directly
        try:
            # Reset magnetometer
            self.bus.write_byte_data(MAG_ADDR, MAG_CNTL3, 0x01)
            time.sleep(0.1)
            
            # Check magnetometer ID
            mag_id = self.bus.read_byte_data(MAG_ADDR, MAG_WHO_AM_I)
            if mag_id != 0x09:  # AK09916 ID
                print(f"Warning: Unexpected magnetometer ID: {hex(mag_id)}")
            else:
                print("Magnetometer ID verified")
            
            # Set magnetometer to continuous mode 4 (100 Hz)
            self.bus.write_byte_data(MAG_ADDR, MAG_CNTL2, 0x08)
            time.sleep(0.1)
            
            print("Magnetometer initialized in bypass mode")
        except Exception as e:
            print(f"Error initializing magnetometer: {e}")
            raise

        print("ICM20948 initialization complete")

    def calibrate(self):
        """Calibrate sensors by calculating offsets from rest position"""
        print("Starting calibration... Keep the sensor still...")
        
        gyro_samples = []
        accel_samples = []
        mag_samples = []
        
        # Collect samples
        for _ in range(self.calibration_samples):
            accel, gyro, mag = self.read_all()
            gyro_samples.append(gyro)
            accel_samples.append(accel)
            mag_samples.append(mag)
            time.sleep(0.01)
        
        # Calculate mean offsets
        self.gyro_offset = np.mean(gyro_samples, axis=0)
        
        # For accelerometer, we only adjust X and Y, keeping Z for gravity
        accel_mean = np.mean(accel_samples, axis=0)
        self.accel_offset[0:2] = accel_mean[0:2]  # Only X and Y
        
        # For magnetometer
        self.mag_offset = np.mean(mag_samples, axis=0)
        
        print("Calibration complete!")
        return True

    def read_mag(self):
        """Read magnetometer data directly through I2C bypass"""
        try:
            data = self.bus.read_i2c_block_data(MAG_ADDR, MAG_HXL, 6)
            mx = struct.unpack('<h', bytes(data[0:2]))[0]
            my = struct.unpack('<h', bytes(data[2:4]))[0]
            mz = struct.unpack('<h', bytes(data[4:6]))[0]
            
            # Check if data is valid (AK09916 specific)
            status = self.bus.read_byte_data(MAG_ADDR, 0x18)  # ST2 register
            if status & 0x08:  # Check magnetic overflow bit
                return np.zeros(3)
                
            return np.array([mx, my, mz]) * self.mag_scale
        except Exception as e:
            print(f"Magnetometer read error: {e}")
            return np.zeros(3)

    def read_all(self):
        self.select_bank(0)
        
        # Read accelerometer and gyroscope
        data = self.read_bytes(B0_ACCEL_XOUT_H, 12)
        ax = struct.unpack('>h', bytes(data[0:2]))[0]
        ay = struct.unpack('>h', bytes(data[2:4]))[0]
        az = struct.unpack('>h', bytes(data[4:6]))[0]
        gx = struct.unpack('>h', bytes(data[6:8]))[0]
        gy = struct.unpack('>h', bytes(data[8:10]))[0]
        gz = struct.unpack('>h', bytes(data[10:12]))[0]

        # Convert to proper units
        accel = np.array([ax/self.accel_scale, ay/self.accel_scale, az/self.accel_scale])
        gyro = np.array([gx/self.gyro_scale, gy/self.gyro_scale, gz/self.gyro_scale])
        gyro = np.radians(gyro)  # Convert to radians/second
        
        # Read magnetometer directly through I2C bypass
        mag = self.read_mag()

        return accel, gyro, mag

def quat2euler(q):
    """
    Convert quaternion to Euler angles (roll, pitch, yaw)
    q = [w, x, y, z]
    """
    # Extract quaternion components
    w, x, y, z = q
    
    # Roll (x-axis rotation)
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = np.arctan2(sinr_cosp, cosr_cosp)
    
    # Pitch (y-axis rotation)
    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = np.copysign(np.pi / 2, sinp)  # Use 90 degrees if out of range
    else:
        pitch = np.arcsin(sinp)
    
    # Yaw (z-axis rotation)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = np.arctan2(siny_cosp, cosy_cosp)
    
    return np.array([roll, pitch, yaw])

class DataSender(Thread):
    def __init__(self, server_url, queue_size=2):  # Reduced queue size
        super().__init__()
        self.queue = Queue(maxsize=queue_size)
        self.server_url = server_url
        self.stop_event = Event()
        self.session = requests.Session()
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.daemon = True

    def run(self):
        while not self.stop_event.is_set():
            try:
                # Always get the most recent data
                data = None
                while not self.queue.empty():
                    try:
                        data = self.queue.get_nowait()
                    except:
                        break
                
                if data is None:
                    time.sleep(0.016)  # Wait a frame if no data
                    continue
                
                try:
                    response = self.session.post(
                        f"{self.server_url}/sensor_data",
                        json=data,
                        timeout=0.2  # Reduced timeout
                    )
                    if response.status_code != 200:
                        print(f"Server error: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    print(f"Connection error: {e}")
                    
            except Exception as e:
                if not self.stop_event.is_set():
                    print(f"Sender thread error: {e}")
                time.sleep(0.016)

    def send_data(self, data):
        # Clear the queue before adding new data
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                break
        
        # Add new data
        try:
            self.queue.put_nowait(data)
        except:
            pass  # Queue is full, skip this update

    def stop(self):
        self.stop_event.set()

def main():
    global q, last_update
    print("Initializing ICM20948...")
    bus = smbus.SMBus(1)
    imu = ICM20948(bus)
    imu.initialize()
    print("ICM20948 initialized successfully")
    
    # Initial calibration
    imu.calibrate()
    
    # Initialize Madgwick with appropriate parameters
    global fuse
    fuse = Madgwick(sampleperiod=0.01, beta=1.0)
    q = np.array([1., 0., 0., 0.])
    last_update = time.time()
    last_print = time.time()
    
    # Initialize data sender thread
    data_sender = DataSender(SERVER_URL)
    data_sender.start()
    print("Data sender thread started")

    try:
        while True:
            try:
                current_time = time.time()
                
                # Read and process sensor data
                accel, gyro, mag = imu.read_all()
                
                # Calculate delta time
                dt = current_time - last_update
                last_update = current_time
                
                # Update filter
                fuse.samplePeriod = dt
                q = fuse.updateMARG(q, 
                                  gyr=gyro, 
                                  acc=accel * 9.81,  # Convert to m/s²
                                  mag=mag)
                
                # Convert quaternion to Euler angles
                roll, pitch, yaw = np.degrees(quat2euler(q))
                
                # Debug output
                if current_time - last_print >= 1.0:
                    print("\nSensor Data:")
                    print(f"Accel: {accel}")
                    print(f"Gyro: {gyro}")
                    print(f"Mag: {mag}")
                    print(f"\nOrientation:")
                    print(f"Roll: {roll:.1f}°")
                    print(f"Pitch: {pitch:.1f}°")
                    print(f"Yaw: {yaw:.1f}°")
                    print(f"Quaternion: {q}")
                    last_print = current_time

                # Send immediate motion data
                game_data = {
                    "o_alpha": yaw,
                    "o_beta": pitch,
                    "o_gamma": roll,
                    "ax": accel[0],
                    "ay": accel[1],
                    "az": accel[2],
                    "quat": [
                        q[0],  # w
                        q[1],  # x
                        q[2],  # y
                        q[3]   # z
                    ],
                    "timestamp": current_time
                }
                data_sender.send_data(game_data)

                # Maintain consistent sampling rate
                elapsed = time.time() - current_time
                if elapsed < 0.01:  # 100Hz target
                    time.sleep(0.01 - elapsed)

            except OSError as e:
                print(f"I2C Error: {e}")
                time.sleep(0.1)
                continue

    except KeyboardInterrupt:
        print("\nProgram stopped by user")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Cleaning up...")
        data_sender.stop()
        data_sender.join(timeout=1.0)
        try:
            bus.close()
        except:
            pass

if __name__ == "__main__":
    main()