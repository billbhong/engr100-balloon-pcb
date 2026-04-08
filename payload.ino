/*
  UMICH ENGR 100.950 "Electronics for Atmospheric and Space Measurements"
  Team 5 Howling Hill Payload Code

  Written by: Bill Hong, University of Michigan

  Features:
  - Optimized GPS, BME680, TMP36, ADXL reading
  - Different reading intervals for each sensor 
  - LED status light for writing to Arduino RAM and to physical SD card
  - Optional serial print for verification
  - Custom GPS logging to get rid of redudant strings when GPS is locked
*/

#include <SPI.h>
#include <SD.h>
#include <Adafruit_Sensor.h>
#include "Adafruit_BME680.h"
#include <SoftwareSerial.h>
SoftwareSerial gps(2, 3); // RX, TX

bool isVerbose = true;

// const int nChars = 500;
// char gps_string[nChars];

const int nChars = 120;
char gps_string[nChars];
int gps_index = 0;
bool gps_ready = false;

void clear_gps_string() {
  for (int i = 0; i < nChars ; i++) gps_string[i] = '\0';
}

void read_gps() {
  // Quickly read any characters that have arrived in the background
  while (gps.available() > 0) {
    char c = gps.read();

    // If we get a newline, the GPS sentence is complete!
    if (c == '\n') {
      gps_string[gps_index] = '\0'; // Null-terminate the string
      gps_index = 0;                // Reset index for the next sentence
      gps_ready = true;             // Flag that a full string is ready to print/save
      break;                        // Exit the while loop so we don't block
    } 
    // Otherwise, add the character to our buffer (ignoring carriage returns)
    else if (c != '\r') {
      gps_string[gps_index] = c;
      gps_index++;
      
      // Prevent buffer overflow if a sentence is somehow too long
      if (gps_index >= nChars - 1) {
        gps_index = nChars - 1; 
      }
    }
  }
}

// --- LED STATUS PINS ---
const int balloonLedPin = 4; // D4 - Indicates Balloon Mode is active
const int sdWriteLedPin = 7; // D7 - Flashes when saving data

// This is the CS pin that the SD Logger is connected to
const int SDLoggerChipSelect = 10;

// This is the CS pin that the BME680 is connected to
const int BMEchipSelect = 9;

// These are the pins your accelerometer lines are connected to
const int xAccelPin = A0;
const int yAccelPin = A2;
const int zAccelPin = A3;

// This is the pin your voltage divider is connected to
const int vDivPin = A6;

const int tmpPin = A1; // TMP36 pin
const float tmpSlope = 105.33;
const float tmpIntercept = -53.7;

// Ohms, R1 = sum of all resistances between Vin and Vout
const float R1 = 1000;

// Ohms, R2 = sum of all resistances between Vout and GND
const float R2 = 1000;

// ***** Enable the following boolean to print raw voltages to the serial monitor for calibration of analog sensors *****
bool calibration_setup      = false; // True for calibration mode (slope = 1, intercept = 0), false for normal operation

// Note that you still need to fill in the slope and intercept values below to prevent an error from the question marks, this
// just overrides those values for calibrating so you don't have to switch all of the pin declarations values back and forth.

float xAccelSlope     = 28.8;
float xAccelIntercept = -48.7;
float yAccelSlope     = 29.3;
float yAccelIntercept = -49.3;
float zAccelSlope     = 29.3;
float zAccelIntercept = -50.3;

bool SerialPrint            = true; // True to print, false for no serial monitor (defaults to true in calibration mode)
// ************************************************** END EDITING **************************************************

// Filename placeholder
char dataFileName[16];

// Global File object so it can stay open
File dataFile; 

// Timing variables for different frequencies
const unsigned long accel_and_tmp_Interval = 20;   // 50 Hz for accelerometer (20ms)
const unsigned long bmeInterval = 500;   // 1 Hz for BME680 (1000ms)
const unsigned long gpsInterval = 5000;   // 1/5 Hz for GPS (5000ms)
const unsigned long flushInterval = 5000; // Save to SD every 5 seconds (5000ms)

unsigned long bmeEndTime = 0;
bool isBmeReading = false;

unsigned long lastAccelTime = 0;
unsigned long lastBMETime = 0;
unsigned long lastGPSTime = 0;
unsigned long lastFlushTime = 0;

// Store BME values globally so the fast loop can write the most recent ones
float bme_temperature = NAN;
float humidity        = NAN;
float pressure        = NAN;

// BME680 object constructor
Adafruit_BME680 bme(BMEchipSelect, &SPI);
void setup() {

  delay(2000);

  Serial.begin(19200);

  // LED
  pinMode(balloonLedPin, OUTPUT);
  pinMode(sdWriteLedPin, OUTPUT);
  // Turn on Balloon Mode LED immediately (Assuming you configure it in setup)
  digitalWrite(balloonLedPin, HIGH);

  if (calibration_setup) {
      // Calibration mode
      SerialPrint = true;
      
      xAccelSlope     = 1.0;
      xAccelIntercept = 0.0;
      yAccelSlope     = 1.0;
      yAccelIntercept = 0.0;
      zAccelSlope     = 1.0;
      zAccelIntercept = 0.0;

      if (SerialPrint) {
        Serial.println(F("Calibration mode enabled."));
      }
  } else {
      if (SerialPrint) {
        Serial.println(F("Calibration mode disabled."));
      }
  }

  if (SerialPrint) {
    if (isVerbose) {
      Serial.println(F("Serial communication initialized."));
    }
  }


  // --- Initialize SD Card on hardware SPI ---
  pinMode(SDLoggerChipSelect, OUTPUT);
  if (!SD.begin(SDLoggerChipSelect)) {
    if (SerialPrint) {
      Serial.println(F("SD initialization failed!"));
    }
    while (true) {}
  }
  if (SerialPrint) {
    Serial.println(F("SD initialization OK."));
  }

  // --- Find next available file name, like "datalog01.csv", "datalog2.csv" ---
  int fileIndex = 1;
  while (true) {
    // Format candidate
    snprintf(dataFileName, sizeof(dataFileName), "data%02d.csv", fileIndex);
    
    // Use this filename if it doesn't exist
    if (!SD.exists(dataFileName)) {
      break;  // Filename chosen
    }
    fileIndex++;  // Increment and try the next number
  }

  // Create chosen file and write header
  dataFile = SD.open(dataFileName, FILE_WRITE); // Assign to global variable
  if (dataFile) {
    dataFile.println(F("Time (ms),Voltage (V),TMP36 (C), BME Temp (C),Pressure (Pa),Humidity (%),xAccel (g),yAccel (g),zAccel(g)"));
    dataFile.flush(); // Flush instead of close! Keeps file open but saves the header.

    if (SerialPrint) {
      Serial.print(F("Created file: "));
      Serial.println(dataFileName);
    }
  } else {
    if (SerialPrint) {
      Serial.print(F("Error1: Can't open "));
      Serial.println(dataFileName);
    }
  }

  // --- Initialize BME680 on software SPI ---
  if (!bme.begin()) {
    if (SerialPrint) {
      Serial.println(F("BME680 initialization failed! Check wiring."));
    }
    while (true) {}
  }
  if (SerialPrint) {
    Serial.println(F("BME680 initialization OK."));
  }

  // *************** BME680 CONFIGURATION ***************
  bme.setTemperatureOversampling(BME680_OS_2X); // 2 samples for temperature oversampling
  bme.setHumidityOversampling(BME680_OS_2X);    // 2 samples for humidity oversampling
  bme.setPressureOversampling(BME680_OS_4X);    // 4 samples for pressure oversampling
  bme.setIIRFilterSize(BME680_FILTER_SIZE_1);   // Filter size for pressure & temperature, set to 0 for OFF

  // If you want to utilize the gas heater, a common setting is 320 C, 150 ms (320, 150)
  bme.setGasHeater(0, 0); // Gas heater settings: 0 C, 0 ms, DISABLED
  // *************** END OF BME680 CONFIGURATION ***************

  gps.begin(9600);
  // set the gps port to listen:
  gps.listen();
  if (isVerbose) Serial.println("GPS is initialized!");  

  if (SerialPrint) {
    Serial.println(F("Setup complete."));
  }
}

void loop() {
  unsigned long currentMillis = millis();

  read_gps();

  // If a full GPS sentence just finished downloading, print/save it
  if (gps_ready) {
    // Check if the newly arrived string starts with "$GPGGA"
    if (strncmp(gps_string, "$GPGGA", 6) == 0) {
      
      // It is a GPGGA string! Now check if 5 seconds have passed since the last log
      if (currentMillis - lastGPSTime >= gpsInterval) {
        lastGPSTime += gpsInterval; // Reset timer and prevent drift
        
        if (SerialPrint && isVerbose) {
          Serial.print(F("GPS: "));
          Serial.println(gps_string);
        }
        
        // Write the raw GPGGA string to the SD card
        if (dataFile) {
          dataFile.println(gps_string);
        }
      }
    }
    
    // reset the flag for next reading
    gps_ready = false; 
  }

  // --- ASYNC BME680 READ ---
  
  // 1. If it's time for a reading, and we aren't already taking one, start it.
  if (currentMillis - lastBMETime >= bmeInterval && !isBmeReading) {
    lastBMETime = currentMillis;
    bmeEndTime = bme.beginReading(); // Returns the time (in millis) when the reading will be done
    if (bmeEndTime != 0) {
      isBmeReading = true; // Flag that the sensor is busy
    } else {
      if (SerialPrint) Serial.println(F("**BME680 Begin Failed**"));
    }
  }

  // 2. If the sensor is busy, but the required time has passed, collect the data.
  if (isBmeReading && currentMillis >= bmeEndTime) {
    if (bme.endReading()) {
      bme_temperature  = bme.temperature; // °C
      humidity         = bme.humidity;    // %
      pressure         = bme.pressure;    // Pa
    } else {
      if (SerialPrint) Serial.println(F("**BME680 End Failed**"));
    }
    isBmeReading = false; // Reset flag so the next interval can start
  }

  // --- READ ACCEL/ANALOG & LOG ---
  if (currentMillis - lastAccelTime >= accel_and_tmp_Interval) {
    lastAccelTime += accel_and_tmp_Interval;

    float vDivVal      = analogRead(vDivPin);
    float vDivVoltage  = (vDivVal * 5.0 / 1023.0) * ((R1 + R2) / R2);

    float tmpV         = analogRead(tmpPin) * 5.0 / 1023.0;
    float tmp          = (tmpSlope * tmpV) + tmpIntercept;

    float xAccelV      = analogRead(xAccelPin) * 5.0 / 1023.0;
    float xAccel       = (xAccelSlope * xAccelV) + xAccelIntercept;

    float yAccelV      = analogRead(yAccelPin) * 5.0 / 1023.0;
    float yAccel       = (yAccelSlope * yAccelV) + yAccelIntercept;

    float zAccelV      = analogRead(zAccelPin) * 5.0 / 1023.0;
    float zAccel       = (zAccelSlope * zAccelV) + zAccelIntercept;

    // Direct printing to SD card (Fixes String Memory Leak & Bottleneck)
    if (dataFile) {
      // Since turning off and on at a high freq, should look like a glow
      digitalWrite(sdWriteLedPin, HIGH); // TURN ON LED before writing

      dataFile.print(currentMillis);    dataFile.print(",");
      dataFile.print(vDivVoltage);      dataFile.print(",");
      dataFile.print(tmp);              dataFile.print(",");
      dataFile.print(bme_temperature);  dataFile.print(",");
      dataFile.print(pressure);         dataFile.print(",");
      dataFile.print(humidity);         dataFile.print(",");
      dataFile.print(xAccel);           dataFile.print(",");
      dataFile.print(yAccel);           dataFile.print(",");
      dataFile.println(zAccel);         // println adds the newline char

      digitalWrite(sdWriteLedPin, LOW); // TURN OFF LED after writing
    }

    // Optional Serial Print for Debugging
    if (SerialPrint) {
      Serial.print(currentMillis);    Serial.print(",");
      Serial.print(vDivVoltage);      Serial.print(",");
      Serial.print(tmp);              Serial.print(",");
      Serial.print(bme_temperature);  Serial.print(",");
      Serial.print(pressure);         Serial.print(",");
      Serial.print(humidity);         Serial.print(",");
      Serial.print(currentMillis);    Serial.print(",");
      Serial.print(xAccel);           Serial.print(",");
      Serial.print(yAccel);           Serial.print(",");
      Serial.println(zAccel);
    }
  }

  // --- FLUSH SD CARD ---
  // This physically saves the data to the card without the heavy delay of closing/reopening
  if (currentMillis - lastFlushTime >= flushInterval) {
    lastFlushTime = currentMillis;
    if (dataFile) {
      dataFile.flush(); 
    }
  }
}