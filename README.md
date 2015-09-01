# udacity-fullstack-p4

Udacity fullstack project #4: Conference Organization App

This is an implementation of the specification for the Conference Organization App, the fourth project of the Udacity Full Stack Web Developer Nanodegree.

The front end is provided by Udacity. All my work is for implementing additional API endpoints and the backend code to implement them.

The following endpoints are implemented per the spec:

* getConferenceSessions(websafeConferenceKey) -- Given a conference, return all sessions
* getConferenceSessionsByType(websafeConferenceKey, typeOfSession) Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)
* getSessionsBySpeaker(speaker) -- Given a speaker, return all sessions given by this particular speaker, across all conferences
* createSession(SessionForm, websafeConferenceKey) -- open only to the organizer of the conference
* addSessionToWishlist(SessionKey) -- adds the session to the user's list of sessions they are interested in attending. You can decide if they can only add conference they have registered to attend or if the wishlist is open to all conferences.
* getSessionsInWishlist() -- query for all the sessions in a conference that the user is interested in
* getFeaturedSpeaker() -- returns the featured speaker announcement from the memcache, if available. The Featured Speaker announcement is added to the memcache if the speaker has more than one session in a given conference, and is posted when a new session containing that speaker is added.

Two additional APIs were implemented to support the new classes:

* getSpeakers(VoidMessage, SpeakerForms) -- Returns all the speakers in the database.
* getSessionsByTopic(topic, SessionForms) -- Returns all the sessions which contain the topic in either the name or highlights.

The following model classes were created to support the new endpoints:
For Sessions:
* Session
* SessionForm
* SessionForms
Sessions are implemented with a conference as an ancestor relation. Sessions are tightly coupled with their conference (a session can't exist in two conferences), so this makes a certain amount of sense. It also gets us strong consistency which will give us more efficient session queries. Sessions are modeled after conferences, with the necessary changes for content, of course.

A few comments on the fields within a session. The localDate field breaks the rule of storing datetimes as UTC. This is simply because I assume that a conference has a physical location, so the local time (at the location) is the only one that matters. This may not be a good assumption if there will be teleconferencing, so it's a design decision that could be revisited. Each session can have multiple speakers (both Wallace and Gromit could both be listed). Speakers (see below) are loosely coupled to the session by maintaining the websafe key for each speaker.

For Speakers
* Speaker
* SpeakerForm
* SpeakerForms
Speakers are implemented as their own kind. This allows us to track other information about the speaker. In this barebones implementation there is only a bio field for biographical information, but adding contact information or a photo would certainly be other reasonable fields.

Speakers are independent, having no ancestral relations. This allows the same speaker to appear in multiple sessions across different conferences.
App Engine application for the Udacity training course.

## Query Related Problem (task 3):

The query relation problem in task 3 is given as: "Let’s say that you don't like workshops and you don't like sessions after 7 pm. How would you handle a query for all non-workshop sessions before 7 pm? What is the problem for implementing this query? What ways to solve it did you think of?"

The basic solution is, of course to query for all sessions where typeOfSession != WORKSHOP, and localTime <= 19:00. The challenge is that Appengine Datastore allows only one inequality per query, so a workaround is needed to support this case. I opted to break the query into to two steps: first, query datastore with one property; then filter the query results to handle the second inequality. In particular, I query by time first (because that allows me to order by time), then iterate over the results, excluding any WORKSHOP sessions that were returned before returning my own api results.

Note that this implementation includes in its results any session that does not have a defined start time.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Requirements
This project was developed on Ubuntu 14.04 using Python 2.7 and Google App Engine 1.9.25.

### Setup Instructions

If you would like to modify the code to run under your own app engine id and make your own changes:

1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

## Installation

* Clone the repo: `git clone https://github.com/barefootlance/udacity-fullstack-p4.git`.
* Install Google App Engine

## Running the project

* `cd <path to>/ud858`

See the Google documentaion on developing and testing at https://cloud.google.com/appengine/docs/python/endpoints/test_deploy. But it that's TL;DR:

* `python <path to>/dev_appserver.py ConferenceCentral_P4` runs the site with the development webserver at localhost:8080
* After the webserver is running, you can access the apis by going to `http://localhost:8080/_ah/api/explorer` in your browser. NOTE: some APIs will require you to authenticate with a Google signin. If you are not signed in you will get a 401 error. To sign in turn the `Authorize requests using OAuth 2.0` slider in the top right corner to On.
* To deploy to appspot, `python <path to>/appcfg.py update ConferenceCentral_P4`.
* To access the upploaded APIs for this implementation: `https://udacity-project-4-1044.appspot.com/_ah/api/explorer`.
