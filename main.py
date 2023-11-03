from flask import Flask, request
import os
import openai
import pinecone

# Twilio API keys stored in environment variables
# Twilio API key docs: https://www.twilio.com/docs/iam/keys/api-key
twilio_api_key = os.environ['TWILIO_API_KEY']
twilio_api_secret = os.environ['TWILIO_API_SECRET']
twilio_account_sid = os.environ['TWILIO_ACCOUNT_SID']


# OpenAI API key stored in environment variables
open_ai_api_key = os.environ['OPENAI']

# Pinecone API key store in evniroment variable
pinecone_api_key = os.environ['PINECONE']
pinecone_environment = 'asia-southeast1-gcp-free'
pinecone.init(pinecone_api_key, environment=pinecone_environment)

# Set the Open API key
openai.api_key = open_ai_api_key


# Set your Twilio Flex Sids
twilio_workspace_sid = ''
twilio_workflow_sid = ''
conversatino_service_sid = ''


# Initiate Twilio Client 
# Get started with Twilio: https://www.twilio.com/try-twilio 

from twilio.rest import Client
twilio_client = Client(twilio_api_key, twilio_api_secret, twilio_account_sid)



def create_app():
    app = Flask(__name__)

    @app.post('/')
    def chat():

        # Parse the incoming request
        # Example: https://www.twilio.com/docs/conversations/conversations-webhooks#onmessageadded
        webhook = request.form.to_dict()
        message_body = webhook['Body']


        # Fetch the conversation using Twilio Conversations API
        # Conversations Docs: https://www.twilio.com/docs/conversations/api/conversation-resource
        conversation_sid = webhook['ConversationSid']
        conversation = twilio_client.conversations.v1.services(
            conversatino_service_sid).conversations(conversation_sid).fetch()


        # If user types @restart, close the conversation
        if message_body.lower() == '@restart':
            conversation.messages.create(
                author='system', body='Restarting conversation')
            conversation.update(state='closed')
            return 'restarted conversation', 200
        

        # Embed the inbound message
        embed_model = 'text-embedding-ada-002'
        querey_embedding = openai.Embedding.create(input=[message_body], engine=embed_model)
        querey_embedding = querey_embedding['data'][0].embedding
        

        # Query the Pinecone database for top_k cosine similarity results
        index = pinecone.Index('demo')
        results = index.query(vector=querey_embedding, top_k=5, include_metadata=True, include_values=True)
        matches = results.get('matches')


        # Make string from matches  
        matched_text = '\n\n'.join([match['metadata']['text'] for match in matches])


        # Give your bot a purpose and personality
        # Prompt engineering best practices: https://help.openai.com/en/articles/6654000-best-practices-for-prompt-engineering-with-openai-api 
        prompt = 'You are a helpful assistant for the city of San Francisco. Users will ask you about parks, recreation, their billing accounts. Please be friendly and kinds and speak with a southern drawl.'


        # Chat GPT needs a list of messages from the system and user
        # Example: https://platform.openai.com/docs/guides/gpt/chat-completions-api
        chat_gpt_messages = [{'role': 'system', 'content': prompt}]
        chat_gpt_messages.append({'role': 'system', 'content': f'Consider the following context in your response: {matched_text}'})


        # Loop through the previous mesages and add them to the Chat GPT messages list
        # Twilio Conversations Message resource: https://www.twilio.com/docs/conversations/api/conversation-message-resource 
        for message in conversation.messages.list(order='desc', limit=6)[::-1]:
            chat_gpt_messages.append({
                'role': 'assistant' if message.author == 'system' else 'user',
                'content': message.body
            })


        # Feed the list of messages to Chat GPT and get response
        response = openai.ChatCompletion.create(
            model="gpt-4", 
            messages=chat_gpt_messages,
            temperature=2.0,
            functions=[
                {
                    "name": "escalate_to_agent",
                    "description": "Escalate the converation to a human. Used when the user wants to speak with a human.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            ]
        )

        res = response['choices'][0]['message']
        print(res)
        function_call = res.get('function_call')

        # Check for Agent Escalation
        if function_call and function_call.get('name') == 'escalate_to_agent':
            print(f'Sending to Flex')
            twilio_client.flex_api.v1.interaction.create(
                channel={
                    "type": "sms",
                    "initiated_by": "customer",
                    "properties": {
                        "media_channel_sid": conversation_sid
                    }
                },
                routing={
                    'properties': {
                        'workspace_sid': twilio_workspace_sid,
                        'workflow_sid': twilio_workflow_sid,
                        'attributes': {

                        }
                    }
                }
            )
            response_message = 'One moment while I connect you with an agent.'
        else:
            response_message = response['choices'][0]['message']['content']
            print(f'Response: {response_message}')


        # Add response message to Twilio Conversation and return 200
        conversation.messages.create(author='system', body=response_message)

        return 'ok', 200

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))
