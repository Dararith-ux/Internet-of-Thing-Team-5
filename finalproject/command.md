// run input img
python3 pic.py --image image3.png --model best_model.onnx

// run the webserver to use real time detection: 
python3 pill_server.py --model best_model.onnx --port 8080