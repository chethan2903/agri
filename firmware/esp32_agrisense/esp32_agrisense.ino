/*
 * AgriSense ESP32 Edge Telemetry Node Firmware
 * Multi-node architecture: assign a unique NODE_ID per physical unit
 * (e.g., "AGRI-001", "AGRI-002", ...). A single ESP32 monitors one
 * localized point; multi-zone fields deploy one node per zone.
 *
 * Connected Hardware Sensors:
 *   - DHT22 (AM2302): +/-0.5 C, +/-2-5% RH, 0-100% RH (GPIO 4)
 *   - Capacitive Soil Moisture v1.2: localized moisture ~8-10 cm depth (GPIO 34)
 *   - MQ-135 Gas / Air Quality Sensor: gas response in PPM (GPIO 32)
 *
 * Optional Hardware Probes (set to true ONLY if physically attached):
 *   - HAS_NPK_PROBE / HAS_PH_PROBE: omitted (null) unless attached so
 *     unmeasured channels are never misrepresented as real readings.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

const char* ssid      = "YOUR_WIFI_NAME";
const char* password  = "YOUR_WIFI_PASSWORD";
const char* serverUrl = "http://192.168.1.50:5000/api/sensor-data";
const char* nodeId    = "AGRI-001";
const char* deviceId  = "AGR-ESP32-NODE1";
const char* siteName  = "Center Zone";
const char* soilType  = "loam"; // sand | loam | clay | silt | peat

#define DHTPIN         4
#define DHTTYPE        DHT22
#define SOIL_PIN       34
#define MQ135_PIN      32
#define SAMPLE_COUNT   5
#define HAS_NPK_PROBE  false
#define HAS_PH_PROBE   false

DHT dht(DHTPIN, DHTTYPE);

// Two-point capacitive calibration baselines (12-bit ESP32 ADC: 0-4095)
const int AIR_VALUE   = 3200; // Dry probe in open air
const int WATER_VALUE = 1300; // Probe immersed to depth mark in water

int readMedianADC(int pin) {
  int samples[SAMPLE_COUNT];
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    samples[i] = analogRead(pin);
    delay(40);
  }
  for (int i = 0; i < SAMPLE_COUNT - 1; i++) {
    for (int j = i + 1; j < SAMPLE_COUNT; j++) {
      if (samples[j] < samples[i]) {
        int tmp = samples[i];
        samples[i] = samples[j];
        samples[j] = tmp;
      }
    }
  }
  return samples[SAMPLE_COUNT / 2];
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  pinMode(SOIL_PIN, INPUT);
  pinMode(MQ135_PIN, INPUT);
  dht.begin();

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n[AgriSense] Wi-Fi Connected!");
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    float temp = NAN;
    float hum  = NAN;
    bool dhtOk = false;

    for (int attempt = 0; attempt < 3; attempt++) {
      temp = dht.readTemperature();
      hum  = dht.readHumidity();
      if (!isnan(temp) && !isnan(hum) && temp >= -40.0 && temp <= 80.0 && hum >= 0.0 && hum <= 100.0) {
        dhtOk = true;
        break;
      }
      delay(2000);
    }

    int rawMoisture = readMedianADC(SOIL_PIN);
    float moisture = ((float)(AIR_VALUE - rawMoisture) / (float)(AIR_VALUE - WATER_VALUE)) * 100.0f;
    moisture = constrain(moisture, 0.0f, 100.0f);

    int rawAQI = readMedianADC(MQ135_PIN);
    float mq135 = map(rawAQI, 200, 3500, 20, 400);
    mq135 = constrain(mq135, 10.0f, 500.0f);

    StaticJsonDocument<512> doc;
    doc["node_id"]          = nodeId;
    doc["device_id"]        = deviceId;
    doc["site_name"]        = siteName;
    doc["soil_type"]        = soilType;
    doc["sensor_ok"]        = dhtOk;
    doc["raw_moisture_adc"] = rawMoisture;
    doc["moisture"]         = moisture;
    doc["mq135"]            = mq135;

    JsonArray measured = doc.createNestedArray("measured_fields");
    measured.add("moisture");
    measured.add("mq135");

    if (dhtOk) {
      doc["temperature"] = temp;
      doc["humidity"]    = hum;
      measured.add("temperature");
      measured.add("humidity");
    } else {
      doc["temperature"] = nullptr;
      doc["humidity"]    = nullptr;
    }

    if (HAS_NPK_PROBE) {
      // Populate from RS-485 NPK probe when attached
      // doc["nitrogen"] = ...; doc["phosphorus"] = ...; doc["potassium"] = ...;
      // measured.add("nitrogen"); measured.add("phosphorus"); measured.add("potassium");
    }
    if (HAS_PH_PROBE) {
      // Populate from calibrated soil pH probe when attached
      // doc["ph"] = ...;
      // measured.add("ph");
    }

    String jsonString;
    serializeJson(doc, jsonString);

    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");
    http.POST(jsonString);
    http.end();
  }
  delay(10000);
}
