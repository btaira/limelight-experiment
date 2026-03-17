Here’s your troubleshooting guide, pulled from Chief Delphi threads (2023–2025), Reddit r/FRC, and the official Limelight docs. It covers 6 major categories across 30+ documented issues:
What’s inside:
	1.	Networking & Connectivity — the #1 category on CD: limelight.local failures, static IP setup, Bonjour conflicts, DHCP failures at competition, LED blink diagnostics, and wiring to PDP (never VRM)
	2.	AprilTag Detection Issues — tx/ty not updating in AprilTag mode (a common gotcha), wrong tag IDs, glare from venue stage lighting & Lexan covers, tag size slider mismatches
	3.	Distance Calculation — unit traps, measurement errors for camera height/pitch/target height, the tan(0) divide-by-zero guard, and why trig distance differs from botpose distance
	4.	Pose Estimation (MegaTag/botpose) — the zero-pose bug that corrupts odometry, MegaTag2 requiring SetRobotOrientation(), camera yaw sign inversions, dual-camera conflicts, and standard deviation tuning
	5.	Performance & Multiple Cameras — JSON parsing slowdown, LL4 thermal throttling, hostname conflicts with multiple Limelights
	6.	Competition Day Checklist — 8-step pre-match verification list​​​​​​​​​​​​​​​​
