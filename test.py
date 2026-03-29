import requests

response = requests.post("http://127.0.0.1:5001/metrics", json={
  "chickens": 20, 
  "anomalies": 10
})

print(response.text)