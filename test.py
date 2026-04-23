import requests

response = requests.post("http://144.37.146.216:5000/capture")

print(response.text)