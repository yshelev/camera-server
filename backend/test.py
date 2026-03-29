import requests

response = requests.post("http://127.0.0.1:5000/metrics", json={
  "people": 20, 
  "fps": 10
})

print(response)