from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse
from core.ai import process_message
from core.knowledge import load_business_data

app = Flask(__name__)
business_data = load_business_data()

@app.route("/voice", methods=['POST'])
def voice():
    user_input = request.form.get("SpeechResult", "")
    response_text = process_message(user_input, business_data)
    vr = VoiceResponse()
    vr.say(response_text)
    return Response(str(vr), mimetype='text/xml')

