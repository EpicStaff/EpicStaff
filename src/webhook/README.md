# How to Run

## Step 1: Start Redis
The service requires a running Redis server. 

## Step 2: Run the Service
`python run.py`
to load variables from system environment 
OR
`python run.py --debug`
to load variables from `debug.env` file

## Testing
### Send a Test Webhook
curl -X POST "https://punctiliously-interfraternal-millicent.ngrok-free.dev/webhooks/1/" -H "Content-Type: application/json" -d "{\"event\": \"test\"}"