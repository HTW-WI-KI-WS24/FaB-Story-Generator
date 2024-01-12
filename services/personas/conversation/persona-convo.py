import os
import uuid

import openai
from flask import Flask, request, flash, render_template, redirect, url_for, current_app
import requests
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()
api_key = os.getenv('OPENAI_API_KEY')
app_secret_key = os.getenv('APP_SECRET_KEY')
openai.api_key = api_key

# Flask app setup
app = Flask(__name__)
app.secret_key = app_secret_key

# Global variables
chromadb_service_url = 'http://persona-persistence:8082'
getPersonaUrl = f'{chromadb_service_url}/getHero/'
personaList = []


# Helper functions
def get_json_response(url, error_message="Failed to retrieve data"):
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        flash(error_message)
        return None


def post_json(url, json_data, headers):
    try:
        response = requests.post(url, json=json_data, headers=headers)
        return response if response.status_code == 200 else None
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Request to {url} failed: {e}")
        return None


@app.route('/showPlaceholders')
def showPlaceholderPersonalities():
    json_data = get_json_response(f'{chromadb_service_url}/getAllPlaceholders', "Failed to retrieve heroes")
    heroes = [{"id": id, **metadata} for id, metadata in zip(json_data.get('heroes', {}).get('ids', []),
                                                             json_data.get('heroes', {}).get('metadatas', []))] \
        if json_data else []
    return render_template('unfinishedHeroes.html', heroes=heroes)


@app.route('/generatePersonality', methods=['POST'])
def generatePersonality():
    hero_data = {
        'id': request.form['heroId'],
        'name': request.form['heroName'],
        'text': request.form['heroText'],
        'designation': request.form['heroDesignation']
    }
    current_app.logger.info(f"Received hero data: {hero_data}")

    response = requests.get(chromadb_service_url + "/getStoriesWithHero/" + hero_data['name'])
    if response.status_code == 200:
        stories_response = response.json().get('stories', {})
        stories_documents = stories_response.get('documents', [])
        stories_metadata = stories_response.get('metadatas', [])
        current_app.logger.info(f"Fetched stories documents: {stories_documents}")
        current_app.logger.info(f"Fetched stories metadata: {stories_metadata}")
    else:
        stories_documents = []
        stories_metadata = []
        current_app.logger.error("Failed to fetch stories or none found")

    prompt = f"Generate a detailed description of personality for a fictional hero based on the following data:\n\n"
    prompt += f"Hero Name: {hero_data['name']}\n"
    prompt += f"Hero Description: {hero_data['text']}\n"
    prompt += f"Hero Class/Talent: {hero_data['designation']}\n\n"
    prompt += "Associated Stories:\n"

    # If you want to include the story content in the prompt, iterate through stories_documents
    for story_content in stories_documents:
        prompt += f"{story_content}\n\n"

    # And if you want to include metadata like title and description, iterate through stories_metadata
    for story_info in stories_metadata:
        prompt += f"- Title: {story_info.get('title', 'No title')}\n"
        prompt += f"  Description: {story_info.get('description', 'No description')}\n\n"

    prompt += "\nThe personality description should include a collection of about 5-7 dominant " \
              "personality traits (you may include negative traits) and how the hero goes about their live." \
              "This is very important." \
              "Start your response with 'Personality:' and end it after you have finished describing the personality." \
              "Here is an example how I want the response to look: " \
              "Personality: (list of 5-7 character traits here). \n(description of personality with about 5 " \
              "Sentences here)"

    current_app.logger.info(f"Generated prompt: {prompt}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {openai.api_key}"
    }
    current_app.logger.info(f"Sending Data to gpt-4")
    payload = {
        "model": "gpt-4-1106-preview",
        "temperature": 0.8,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 2000
    }

    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        if response.status_code == 200:
            response_json = response.json()
            generated_personality = response_json['choices'][0]['message']['content'] if response_json.get(
                'choices') else 'No content'
            current_app.logger.info(f"Generated personality: {generated_personality}")
        else:
            error_message = f"Error from GPT API: Status Code {response.status_code}, Response: {response.text}"
            current_app.logger.error(error_message)
            generated_personality = f"Error generating personality. API response status: {response.status_code}"
    except requests.exceptions.RequestException as e:
        error_message = f"Request to GPT API failed: {e}"
        current_app.logger.error(error_message)
        generated_personality = f"Error generating personality. Exception: {e}"

    flash(generated_personality)
    return render_template('approvePersonality.html', hero=hero_data, personality=generated_personality)


@app.route('/updateHero', methods=['POST'])
def updateHero():
    hero_data = {
        'id': request.form['heroId'],
        'name': request.form['heroName'],
        'text': request.form['heroText'],
        'designation': request.form['heroDesignation'],
        'personality': request.form['personality']
    }
    # Make POST request to update hero in the database
    response = requests.post(chromadb_service_url + "/updateHero", json=hero_data,
                             headers={'Content-Type': 'application/json'})
    if response.status_code == 200:
        flash('Hero updated successfully!')
    else:
        flash('Failed to update hero.')

    return redirect(url_for('showPlaceholderPersonalities'))


@app.route('/createConversation', methods=['GET'])
def createConversation():
    json_data = get_json_response(f'{chromadb_service_url}/getAllHeroes', "Failed to retrieve heroes")
    if json_data:
        hero_metadatas = json_data.get('heroes', {}).get('metadatas', [])
        hero_names_set = {hero['name'] for hero in hero_metadatas}  # Use a set for unique names
        hero_names = list(hero_names_set)  # Convert the set back to a list for rendering
        hero_names.sort()
    else:
        hero_names = []
    return render_template('createConversation.html', hero_names=hero_names)


@app.route('/sendConversation', methods=['POST'])
def sendConversation():
    Worldbuilding = get_story("The Land of Rathe")
    participatingCharacters = request.form['selectedHeroes'].split(',')
    region = request.form['selectedRegion']
    settingDetails = request.form['settingDetails']
    styles = ', '.join(request.form['selectedStyles'].split(','))

    character_query_response = query_interacting_heroes(participatingCharacters)
    region_query_response = query_region(region, settingDetails, styles)

    # Process queriedCharacterData to handle nested list structure
    queriedCharacterData_list = character_query_response.get('documents', []) if character_query_response else []
    queriedCharacterData = ""
    if queriedCharacterData_list and isinstance(queriedCharacterData_list[0], list):
        queriedCharacterData = ' '.join(queriedCharacterData_list[0])
    else:
        queriedCharacterData = "No additional character data found."

    # Process Region Data in a similar way
    queriedRegionData_list = region_query_response.get('documents', []) if region_query_response else []
    queriedRegionData = ""
    if queriedRegionData_list and isinstance(queriedRegionData_list[0], list):
        queriedRegionData = ' '.join(queriedRegionData_list[0])
    else:
        queriedRegionData = "No additional region data found."

    prompt = f"I want you to write a story set in this world:\n{Worldbuilding}\n" \
             f"It is set in a region called {region}. Here is some additional information about {region}:\n" \
             f"{queriedRegionData}\n" \
             f"The Characters for this story are:\n{', '.join(participatingCharacters)}\n" \
             f"Here is additional context for you about the characters: {queriedCharacterData}\n\n" \
             f"Here is something I definitely want for the story: {settingDetails}\n" \
             f"The story should be written to be {styles}.\n" \
             f"Write about 1000-1500 words. Your message should be in this format: \n <your story> \nTitle: " \
             f"<a title>\nDescription: <a description in one sentence>, " \
             f"Title and Description should be the last two lines of your messages."

    current_app.logger.info(f"Generated prompt: {prompt}")
    generated_story = generate_story_with_openai(prompt)
    title, description = parse_title_and_description(generated_story)

    # Create the JSON payload for saving the story
    story_id = generate_uuid(title)  # Generate a new UUID for the story
    story_data = {
        'documents': [generated_story],
        'metadatas': [{
            'kind': 'story',
            'title': title,
            'description': description,
            **{character.lower(): character for character in participatingCharacters}
        }],
        'ids': [story_id]
    }

    current_app.logger.info(f"Sending data to persistence service: {story_data}")
    # Send the story data to the /saveStory endpoint
    save_story_response = requests.post(
        f'http://persona-persistence:8082/saveStory',
        json=story_data
    )

    # Check if the story was saved successfully
    if save_story_response.status_code == 200:
        flash('Story saved successfully!')
    else:
        flash('Failed to save story. Please try again.')

    return render_template("generatedStory.html", generated_story=generated_story, story_data=story_data)


def get_story(title):
    url = chromadb_service_url + "/getStory/" + title
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        documents = data.get('story', {}).get('documents', [])
        return documents
    else:
        print("Failed to retrieve story or story not found")
        return []


def query_interacting_heroes(character_list):
    query_text = "What are interactions between " + ", ".join(character_list)
    n_results = len(character_list) + 5
    try:
        response = requests.post(
            chromadb_service_url + '/queryChromaDB',
            json={'query_texts': [query_text], 'n_results': n_results},
            headers={"Content-Type": "application/json"}
        )
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        current_app.logger.error(f"Error querying character interactions: {e}")
        return None


def query_region(region, setting, style):
    query_text = "Give me some information about " + region + " in regards to " + setting + " in a " + style + " Style."
    n_results = 10

    # Check for specific region names and adjust if necessary
    if region == "The Demonastery":
        region = "Demonastery"
    elif region == "The Pits":
        region = "Pits"

    try:
        response = requests.post(
            chromadb_service_url + '/queryChromaDB',
            json={'query_texts': [query_text], 'n_results': n_results, 'where': {"region": region}},
            headers={"Content-Type": "application/json"}
        )
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        current_app.logger.error(f"Error querying region information: {e}")
        return None


def generate_story_with_openai(prompt):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {openai.api_key}"}
    payload = {
        "model": "gpt-4-1106-preview", "temperature": 0.8,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000
    }
    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        if response.status_code == 200:
            response_json = response.json()
            return response_json['choices'][0]['message']['content'] if response_json.get('choices') else 'No content'
        else:
            current_app.logger.error(
                f"Error from GPT API: Status Code {response.status_code}, Response: {response.text}")
            return f"Error generating story. API response status: {response.status_code}"
    except Exception as e:
        current_app.logger.error(f"Error generating story: {e}")
        return f"Error generating story: {e}"


def parse_title_and_description(story_text):
    # Regular expression pattern to match the title and description
    pattern = r'\nTitle: (.+)\nDescription: (.+)$'

    # Search for the pattern at the end of the string
    match = re.search(pattern, story_text)

    # If a match is found, extract title and description
    if match:
        title = match.group(1).strip()
        description = match.group(2).strip()
        return title, description
    else:
        # If no match is found, return None or some default values
        return None, None


def generate_uuid(name):
    # Generate a UUID based on the SHA-1 hash of a namespace identifier and a name
    name_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, name)
    return str(name_uuid)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8081)
