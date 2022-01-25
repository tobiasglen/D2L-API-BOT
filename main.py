import json
import os
import sys
import urllib.parse
from lxml import etree
import requests

# Get absolute path of the script
script_path = os.path.dirname(os.path.realpath(__file__))


# Check if json config file exists
if not os.path.isfile(script_path + '/d2l-bot-auth.json'):
    create_json_file = open(script_path + '/d2l-bot-auth.json', 'w')
    json_obj = {
        "username": "",
        "password": "",
        "school_url": ""
    }
    # Write json object to file
    json.dump(json_obj, create_json_file, indent=4)
    create_json_file.close()
    sys.exit(f'Created the following file:\n{script_path}/d2l-bot-auth.json\nPlease fill in the username, password, and school_url')
else:
    for req_key in ['username', 'password', 'school_url']:
        if req_key not in json.load(open(script_path + '/d2l-bot-auth.json')):
            sys.exit(f'The following key is missing in the json file:\n{req_key}')

user_details = json.load(open(script_path + '/d2l-bot-auth.json'))

f = user_details["school_url"]

session = requests.Session()


def auth():
    # Load the session data from the JSON file
    # json_file = open(script_path + '/d2l-bot-auth.json', 'r')
    # json_data = json.load(json_file)


    if "SESS" in user_details:
        for sess_k, sess_v in user_details["SESS"].items():
            session.cookies[sess_k] = sess_v
    # json_file.close()

    # Try making a request to the server to see if we are still logged in
    whoami = session.get(f'{user_details["school_url"]}/d2l/api/lp/1.26/users/whoami')

    try:
        auth_method = "existing session"
        whoami.raise_for_status()
        return True, whoami.json(), auth_method

    except requests.exceptions.HTTPError as e:
        auth_method = "fresh login"
        print("Error: " + str(e))

        # Clear the session cookies
        session.cookies.clear()

        # If we are not logged in, log in
        initial_request = session.get(user_details["school_url"])

        # verify the cookie JSESSIONID is in the response
        if 'JSESSIONID' not in session.cookies:
            return False, 'JSESSIONID not in session.cookies', auth_method

        if initial_request.history:
            print("Request was redirected to: " + initial_request.url)

            login_page = session.get(initial_request.url)
            tree = etree.HTML(login_page.text)

            try:
                le = tree.xpath('//*[@name="execution"]/@value')[0]
            except:
                return False, 'execution not found in login page', auth_method

            # Now, POST to the login page
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:96.0) Gecko/20100101 Firefox/96.0',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Content-Type': 'application/x-www-form-urlencoded',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'TE': 'trailers',
                'Cookie': f'JSESSIONID={session.cookies["JSESSIONID"]}'
            }

            payload = f'username={user_details["username"]}&password={urllib.parse.quote(user_details["password"])}&execution={le}&_eventId=submit'

            test = session.post(initial_request.url, headers=headers, data=payload)
            # print(test.text)

            saml_search = etree.HTML(test.text)
            try:
                SAMLResponse = saml_search.xpath('//*[@name="SAMLResponse"]/@value')[0]
            except:
                return False, 'SAMLResponse not found in login page', auth_method

            # print(f'SAMLResponse: {urllib.parse.quote(SAMLResponse)}')

            # Now, POST to the login page
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            payload = f'SAMLResponse={urllib.parse.quote(SAMLResponse)}'
            if session.post(f'{user_details["school_url"]}/d2l/lp/auth/login/samlLogin.d2l', headers=headers, data=payload, cookies=session.cookies).ok:

                # Write the new session data to the file
                with open(script_path + '/d2l-bot-auth.json', 'w') as outfile:
                    new_sess = {
                        "username": user_details['username'],
                        "password": user_details['password'],
                        "school_url": user_details['school_url'],
                        "SESS": session.cookies.get_dict()
                    }
                    json.dump(new_sess, outfile, indent=4)

                return True, session.get(f'{user_details["school_url"]}/d2l/api/lp/1.26/users/whoami').json(), auth_method

            else:
                return False, 'Login failed', auth_method



# Call auth() function to login & load the session data
login_status, resp, method = auth()

if not login_status:
    sys.exit(f'Login failed: {resp}')

# ---------------------- If we get here, we are logged in! ---------------------- #
print(f'\nLogged in as {resp["FirstName"]} {resp["LastName"]} via {method}\n')

# Set the user ID (needed for some API calls such as grade info)
user_id = resp['Identifier']


def get_grades(course_id):
    course_grades = session.get(f'{user_details["school_url"]}/d2l/api/le/1.41/{course_id}/grades/values/{user_id}/')
    # Make sure we got a 200 response
    try:
        course_grades.raise_for_status()
        grades_json = course_grades.json()
        # TODO - For grade's we have 2 types: Category and Numeric (e.g. Code Listings --> Code Listing I - Ch 12) (Not sure if all instructors are this organized so for now we'll just use the numeric grades)
        parsed_grades = []
        for grade in grades_json:
            if grade['GradeObjectTypeName'] == 'Numeric':
                parsed_grade_obj = {
                    'Name': grade['GradeObjectName'],
                    'DisplayedGrade': str(grade['DisplayedGrade']).replace(' ', ''),
                    'Points': grade['PointsNumerator'],
                    'Total': int(grade['PointsDenominator']),
                    'ID': grade['GradeObjectIdentifier'],
                }
                parsed_grades.append(parsed_grade_obj)

        return True, parsed_grades
    except requests.exceptions.HTTPError as e:
        print(f'Unable to get course list: {e}')
        return False, None


def get_course_list():
    my_enrollments = session.get(f'{user_details["school_url"]}/d2l/api/lp/1.26/enrollments/myenrollments/')
    # Make sure we got a 200 response
    try:
        my_enrollments.raise_for_status()
        return True, my_enrollments.json()
    except requests.exceptions.HTTPError as e:
        print(f'Unable to get course list: {e}')
        return False, None


# Get the latest course assuming its type/name is not "Group"
course_list_status, course_list_json = get_course_list()

if course_list_status:
    # Loop through the courses from more recent to oldest
    for course in reversed(course_list_json["Items"]):
        if course["OrgUnit"]["Type"]["Name"] != "Group":
            print('------------ Most recent course ------------')
            print(f'Name: {course["OrgUnit"]["Name"]}')
            print(f'Course ID: {course["OrgUnit"]["Id"]}')
            print(f"Started: {course['Access']['StartDate']}\n")

            # Get the grades for the course
            get_grades_status, grades = get_grades(course["OrgUnit"]["Id"])
            if get_grades_status:
                print(f'You currently have {len(grades)} grades in this course:')
                for grade in grades:
                    print(f'{grade["Name"]} || {grade["DisplayedGrade"]} || ({grade["Points"]}/{grade["Total"]})')
            break
