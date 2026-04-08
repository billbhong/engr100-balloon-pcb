# Howling Hill Payload Firmware
**UMich ENGR 100.950: Electronics for Atmospheric and Space Measurements**

Flight software for Team 5's high-altitude balloon payload. This code handles asynchronous, multi-rate data collection from various atmospheric and kinetic sensors, logging the telemetry to an onboard SD card for post-flight analysis. 

## Key Features
* **Multi-Rate Sampling:** Uses non-blocking timer loops to read the accelerometer and TMP36 at 50 Hz, BME680 at 1 Hz, and GPS at 0.2 Hz.
* **Smart GPS Parsing:** Buffers serial data in the background and filters exclusively for `$GPGGA` strings to save memory and SD space.
* **Optimized Data Logging:** Utilizes `dataFile.flush()` every 5 seconds rather than repeatedly opening and closing the file to prevent data loss and write bottlenecks.
* **Built-in Calibration Mode:** A toggleable state (`calibration_setup`) that outputs raw analog voltages instead of converted values for easy pre-flight sensor calibration.
* **Visual Telemetry:** LED status indicators for overall system health and active SD card writes.

## Hardware Pinout

| Component | Pin(s) | Notes |
| :--- | :--- | :--- |
| **GPS Module** | D2 (RX), D3 (TX) | SoftwareSerial |
| **SD Card Logger** | D10 (CS) | Hardware SPI |
| **BME680** | D9 (CS) | Hardware SPI |
| **ADXL Accelerometer** | A0 (X), A2 (Y), A3 (Z) | Analog |
| **TMP36 Temp Sensor** | A1 | Analog |
| **Voltage Divider** | A6 | Analog |
| **Status LEDs** | D4 (Mode), D7 (SD Write) | Digital Output |

## Dependencies
This project requires the following libraries, which can be installed via the Arduino Library Manager:
* `SPI`, `SD`, and `SoftwareSerial` (Arduino Built-in)
* `Adafruit Unified Sensor`
* `Adafruit BME680 Library`