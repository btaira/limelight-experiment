# Limelight AprilTag Tracker

### FRC — Python · NetworkTables + HTTP · Live Dashboard

-----

## What it does

- Connects to your Limelight via **HTTP REST** (laptop direct) and/or **NetworkTables** (on-robot)
- Detects AprilTags and calculates:
  - **Distance** to tag (meters, feet, inches)
  - **Tag ID**
  - **TX / TY angles**
  - **Tag orientation** (pitch, yaw, roll)
  - **Robot field pose** (botpose_wpiblue)
- Serves a **live web dashboard** at `http://localhost:5000`

-----

## Setup

### 1. Install dependencies

```bash
pip install flask flask-cors requests

# For NetworkTables support (pick one):
pip install robotpy-ntcore        # recommended
# OR
pip install pynetworktables
```

### 2. Configure your settings

Edit the `Config` class at the top of `limelight_tracker.py`:

```python
LIMELIGHT_IP          = "10.TE.AM.11"   # Your Limelight's IP
NT_SERVER_IP          = "10.TE.AM.2"    # RoboRIO IP

CAMERA_HEIGHT_METERS  = 0.60    # Measure from floor to camera lens
CAMERA_PITCH_DEGREES  = 25.0    # How many degrees camera tilts up
TARGET_HEIGHT_METERS  = 1.45    # Height of AprilTag center (FRC 2024 speaker)
```

### 3. Run

```bash
python limelight_tracker.py
```

Then open **http://localhost:5000** in your browser.

-----

## Command-line options

```
--limelight  192.168.1.11   Override Limelight IP
--rio        10.49.36.2     Override RoboRIO/NT server IP
--port       8080           Change dashboard port
--no-http                   Disable HTTP polling
--no-nt                     Disable NetworkTables
```

Examples:

```bash
# Laptop connected directly to Limelight over USB/ethernet
python limelight_tracker.py --limelight 10.0.0.2 --no-nt

# Competition robot (both sources)
python limelight_tracker.py --limelight 10.49.36.11 --rio 10.49.36.2

# Custom port
python limelight_tracker.py --port 8080
```

-----

## Distance Calculation

Uses the standard FRC trigonometry formula:

```
distance = (target_height - camera_height) / tan(camera_pitch + ty)
```

**To get accurate distances**, measure:

- `CAMERA_HEIGHT_METERS` — vertical distance from floor to lens
- `CAMERA_PITCH_DEGREES` — how far the camera tilts upward (0 = horizontal)
- `TARGET_HEIGHT_METERS` — center height of the AprilTag from the floor
  - FRC 2024 Speaker tags: ~1.45 m
  - FRC 2024 Amp tag: ~1.36 m
  - Check your game manual for exact values

-----

## Limelight Setup (on the Limelight itself)

1. Go to `http://<limelight-ip>:5801` (Limelight web UI)
1. Set **Pipeline Type** to `AprilTag`
1. Enable `botpose` output if you want field pose estimation
1. Set your **team number** in the Limelight settings for correct NetworkTables table name

-----

## API Endpoints

|Endpoint          |Description                    |
|------------------|-------------------------------|
|`GET /`           |Live dashboard UI              |
|`GET /api/latest` |Latest detection as JSON       |
|`GET /api/history`|Last 100 readings as JSON array|

-----

## Troubleshooting

|Problem               |Fix                                                 |
|----------------------|----------------------------------------------------|
|`ntcore not installed`|Run `pip install robotpy-ntcore`                    |
|HTTP returns nothing  |Check Limelight IP, ensure port 5807 is open        |
|Distance is wrong     |Re-measure camera height and pitch angle            |
|Tag ID always -1      |Make sure Limelight pipeline is set to AprilTag mode|
