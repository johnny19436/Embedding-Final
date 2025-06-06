import smbus2
import time
import struct
import requests
import math

# Server configuration
SERVER_URL = "http://localhost:8000"

ICM20948_ADDR = 0x68
bus = smbus2.SMBus(1)

REG_BANK_SEL = 0x7F

# Registers
ACCEL_XOUT_H = 0x2D
GYRO_XOUT_H = 0x33
WHO_AM_I = 0x00

# Calibration offsets
acc_offset = [0.02, 0.0, 0.0]  # g
gyro_offset = [0.0, 0.0, 0.8]  # deg/s
dt = 0.1  # 0.1 second per loop

velocity = [0.0, 0.0, 0.0]  # m/s
distance = [0.0, 0.0, 0.0]  # m
angles = [0.0, 0.0, 0.0]  # roll, pitch, yaw (degrees)

def select_bank(bank):
    bus.write_byte_data(ICM20948_ADDR, REG_BANK_SEL, bank << 4)

def read_i2c_word(reg):
    high = bus.read_byte_data(ICM20948_ADDR, reg)
    low = bus.read_byte_data(ICM20948_ADDR, reg + 1)
    value = struct.unpack('>h', bytes([high, low]))[0]
    return value

def initialize_icm20948():
    select_bank(0)
    whoami = bus.read_byte_data(ICM20948_ADDR, WHO_AM_I)
    if whoami != 0xEA:
        print(f"Unexpected WHO_AM_I value: {hex(whoami)}")
    else:
        print("ICM20948 detected")
    bus.write_byte_data(ICM20948_ADDR, 0x06, 0x01)  # Wake up (PWR_MGMT_1)

initialize_icm20948()

try:
    while True:
        select_bank(0)

        # Read accelerometer data
        acc_raw = [read_i2c_word(ACCEL_XOUT_H + i*2) for i in range(3)]
        acc_g = [acc_raw[i] / 16384.0 - acc_offset[i] for i in range(3)]
        acc_ms2 = [g * 9.81 for g in acc_g]

        # Read gyroscope data
        gyro_raw = [read_i2c_word(GYRO_XOUT_H + i*2) for i in range(3)]
        gyro_dps = [gyro_raw[i] / 131.0 - gyro_offset[i] for i in range(3)]

        # Integrate to get angles
        for i in range(3):
            velocity[i] += acc_ms2[i] * dt
            distance[i] += velocity[i] * dt + 0.5 * acc_ms2[i] * dt * dt
            angles[i] += gyro_dps[i] * dt

        roll, pitch, yaw = angles

        # Prepare data for sending
        game_data = {
            "o_alpha": yaw,       # yaw
            "o_beta": pitch,      # pitch
            "o_gamma": roll,      # roll
            "ax": acc_g[0],       # X acceleration (g)
            "ay": acc_g[1],       # Y acceleration (g)
            "az": acc_g[2],       # Z acceleration (g)
            "pressure": 0.0,      # placeholder
            "temperature": 0.0    # placeholder
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

        # Debug output
        print(f"Acc (g): X={acc_g[0]:.2f}, Y={acc_g[1]:.2f}, Z={acc_g[2]:.2f}")
        print(f"Gyro (deg/s): X={gyro_dps[0]:.2f}, Y={gyro_dps[1]:.2f}, Z={gyro_dps[2]:.2f}")
        print(f"Angles: Roll={roll:.2f}, Pitch={pitch:.2f}, Yaw={yaw:.2f}")
        print("-" * 60)

        time.sleep(dt)

except KeyboardInterrupt:
    print("Stopped by user.")
except Exception as e:
    print(f"Error: {e}")
finally:
    print("Cleaning up.")