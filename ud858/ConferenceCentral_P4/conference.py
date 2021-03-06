#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime
from datetime import time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import SessionType
from models import WebsafeConferenceKeyMessage
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms
from models import WebsafeSessionKeyMessage

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKER"

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "highlights": [ "Default", "Highlights" ],
    "duration": "01:00", # one hour
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

WEBSAFE_CONFERENCE_KEY_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    )

CONFERENCE_SESSIONS_BY_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2)
    )

SPEAKER_SESSIONS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSpeakerKey=messages.StringField(1)
    )

SESSION_TOPIC_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    topic=messages.StringField(1)
    )

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

WISHLIST_POST_REQUEST = endpoints.ResourceContainer(
    websafeSessionKey=messages.StringField(1, required=True),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Speaker objects - - - - - - - - - - - - - - - - - - -

    def _copySpeakerToForm(self, speaker):
        """Copy relevant fields from Speaker to SpeakerForm."""
        sf = SpeakerForm()
        for field in sf.all_fields():
            if hasattr(speaker, field.name):
                setattr(sf, field.name, getattr(speaker, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, speaker.key.urlsafe())
        sf.check_initialized()
        return sf


    def _createSpeakerObject(self, request):
        """Create or update Speaker object, returning SpeakerForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        if not request.displayName:
            raise endpoints.BadRequestException("Speaker 'displayName' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # this is automatically generated for display but should
        # be ignored if it is input.
        del data['websafeKey']

        # Now create the speaker key.
        # NOTE: allocate_ids returns a list, so take the first element.
        speaker_id = Speaker.allocate_ids(size=1)[0]
        speaker_key = ndb.Key(Speaker, speaker_id)
        data['key'] = speaker_key

        # create Speaker, send email to creator confirming
        # creation of Speaker & return (modified) SpeakerForm
        Speaker(**data).put()
        taskqueue.add(params={'email': user.email(),
            'speakerInfo': repr(request)},
            url='/tasks/send_speaker_confirmation_email'
        )
        return request


    @endpoints.method(SpeakerForm, SpeakerForm,
                  path='speaker/create',
                  http_method='POST',
                  name='createSpeaker')
    def createSpeaker(self, request):
        """Create new speaker."""
        # only authenticated users can create speakers
        # TODO: should we track the user who entered the speaker?
        # maybe filter for users who have created at least one conference.
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        speaker = self._createSpeakerObject(request)
        return speaker


    @endpoints.method(message_types.VoidMessage, SpeakerForms,
        path='speaker',
        http_method='POST', name='getSpeakers')
    def getSpeakers(self, request):
        """Return all the speakers."""

        # create ancestor query for all key matches for this conference
        speakers = Speaker.query()

        # return set of ConferenceForm objects per Conference
        return SpeakerForms(
            items=[self._copySpeakerToForm(speaker) for speaker in speakers]
        )


    @endpoints.method(SPEAKER_SESSIONS_GET_REQUEST, SessionForms,
            path='speaker/{websafeSpeakerKey}/session',
            http_method='POST',
            name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Return all the sessions for a speaker."""

        # Make sure the speaker exists
        speaker = ndb.Key(urlsafe=request.websafeSpeakerKey).get()
        if not speaker:
            raise endpoints.NotFoundException(
                'No speaker found with key: %s' % request.websafeSpeakerKey)

        # create ancestor query for all key matches for this conference
        speaker_id = speaker.key.id()
        sessions = Session.query().filter(speaker_id == Session.speakerIds)

        # return set of ConferenceForm objects per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# - - - Session objects - - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date') or \
                   field.name.endswith('Time') or \
                   field.name == 'duration':
                    setattr(sf, field.name, str(getattr(session, field.name)))
                elif field.name == 'typeOfSession':
                    value = getattr(session, field.name)
                    if value:
                        value = str(getattr(session, field.name))
                    else:
                        value = 'NOT_SPECIFIED'
                    setattr(sf, field.name, getattr(SessionType, value))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == 'websafeKey':
                setattr(sf, field.name, session.key.urlsafe())
            elif field.name == 'conferenceWebsafeKey':
                key = session.key.parent()
                if key:
                    setattr(sf, field.name, key.urlsafe())
        sf.check_initialized()
        return sf


    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # get the conference from the websafe key
        conference = ndb.Key(urlsafe=request.websafeConferenceKey).get()

        # NOTE: this sould be shielded by the API methods, but we
        # will check here, just to be sure.
        if not conference:
            raise endpoints.BadRequestException("Session conference not found.")

        if conference.organizerUserId != user_id:
            raise endpoints.BadRequestException("You may only create sessions if you created the conference.")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # add default values for those missing (both data model & outbound Message)
        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])

        # convert dates from strings to Date objects
        if data['localDate']:
            data['localDate'] = datetime.strptime(data['localDate'][:10], "%Y-%m-%d").date()
            if conference.startDate and \
               data['localDate'] < conference.startDate:
                    raise endpoints.BadRequestException("Session 'localDate': not within conference dates.")
            if conference.endDate and \
               data['localDate'] > conference.endDate:
                    raise endpoints.BadRequestException("Session 'localDate': not within conference dates.")

        # convert times from strings to Time objects
        if data['duration']:
            data['duration'] = datetime.strptime(data['duration'][:5], "%H:%M").time()
        if data['localTime']:
            data['localTime'] = datetime.strptime(data['localTime'][:5], "%H:%M").time()

        # convert the session type from enum to string
        if data['typeOfSession']:
            data['typeOfSession'] = str(data['typeOfSession'])
        else:
            data['typeOfSession'] = 'NOT_SPECIFIED'

        # Now create the session key.
        # We want an ancestor relationship with the conference. This
        # will give us strong consistency and make for efficient
        # querying of sessions by conference.
        # In order to establish an ancestor relationship we need to:
        # 1) get the key for the conference
        conference_key = conference.key
        # 2) create an id for the session
        # NOTE: allocate_ids returns a list, so take the first element.
        session_id = Session.allocate_ids(size=1, parent=conference_key)[0]
        # 3) create the session key
        session_key = ndb.Key(Session, session_id, parent=conference_key)
        # 4) and then we'll save the key away
        data['key'] = session_key

        # toss the websafe key
        del data['conferenceWebsafeKey']

        # get rid of the websafeConferenceKey that was passed in
        del data['websafeConferenceKey']

        # delete the websafe key. We already have the id.
        del data['websafeKey']

        # create Session, send email to organizer confirming
        # creation of Session & return websafe conference key
        Session(**data).put()

        taskqueue.add(params={'email': user.email(),
            'sessionInfo': repr(request)},
            url='/tasks/send_session_confirmation_email'
        )

        # If there is more than one session by this speaker at this
        # conference, also add a new Memcache entry that features the
        # speaker and session names.
        # NOTE: we allow for multiple speakers, but this reports only
        # the first one.
        print data['speakerWebsafeKeys']
        for speaker_wsk in data['speakerWebsafeKeys']:
            sessions = Session.query(ancestor=conference_key).filter(Session.speakerWebsafeKeys==speaker_wsk).fetch()
            if sessions and len(sessions) > 1:
                speaker = ndb.Key(urlsafe=speaker_wsk).get()
                self.cacheFeaturedSpeaker(speaker, sessions)
                break

        return request


    @endpoints.method(SESSION_POST_REQUEST, WebsafeConferenceKeyMessage,
                      path='conference/{websafeConferenceKey}/session/create',
                      http_method='POST',
                      name='createSession')
    def createSession(self, request):
        """Create new session."""
        conference = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conference:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        session = self._createSessionObject(request)
        result = WebsafeConferenceKeyMessage()
        result.websafeConferenceKey = request.websafeConferenceKey
        return result


    @endpoints.method(WEBSAFE_CONFERENCE_KEY_GET_REQUEST, SessionForms,
        path='conference/{websafeConferenceKey}/session',
        http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return all the sessions for a conference."""

        # Make sure the conference exists
        conference = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conference:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # create ancestor query for all key matches for this conference
        sessions = Session.query(ancestor=conference.key)

        # return set of ConferenceForm objects per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(CONFERENCE_SESSIONS_BY_TYPE_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/session/type/{typeOfSession}',
            http_method='POST',
            name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return all the sessions for a conference."""

        # Make sure the conference exists
        conference = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conference:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # create ancestor query for all key matches for this conference
        sessions = Session.query(ancestor=conference.key).filter(Session.typeOfSession==request.typeOfSession)

        # return set of ConferenceForm objects per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


    @endpoints.method(SESSION_TOPIC_GET_REQUEST, SessionForms,
            path='session/topic',
            http_method='GET',
            name='getSessionsByTopic')
    def getSessionsByTopic(self, request):
        """Return sesssions where the title or the highlights
        contain the given topic keyword.
        """

        lowerTopic = request.topic.lower()
        sessions = []
        for session in Session.query():
            if lowerTopic in session.name.lower():
                sessions.append(session)
            elif session.highlights:
                for highlight in session.highlights:
                    if lowerTopic in highlight.lower():
                        sessions.append(session)
                        break

        # return set of ConferenceForm objects per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='session/getNonWorkshopsBefore7',
            http_method='POST',
            name='getNonWorkshopsBefore7')
    def getNonWorkshopsBefore7(self, request):
        """Return sesssions where the title or the highlights
        contain the given topic keyword.
        """
        # NOTE: we want "localTime < 7pm and session is not a workshop",
        # however, we can only have one inequality per query, so we
        # query on time first (so that we can sort on it), and then
        # filter the workshop sessions out with an in-memory loop.
        # ALSO NOTE that we allow None session types and times through.
        sevenPM = time(19)
        sessions = Session.query(not Session.localTime or Session.localTime <= sevenPM) \
                          .order(Session.localTime)

        result = []
        for session in sessions:
            # skip workshop sessions
            if session.typeOfSession and session.typeOfSession == 'WORKSHOP':
                continue
            result.append(session)

        # return set of ConferenceForm objects per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in result]
        )

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

    @endpoints.method(WISHLIST_POST_REQUEST, ProfileForm,
            path='profile/wishlist',
            http_method='POST',
            name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Adds a session to the user wishlist and returns the
        updated profile.
        """
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # Make sure the session exists
        session_key = ndb.Key(urlsafe=request.websafeSessionKey)
        session = session_key.get()
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.websafeSessionKey)

        # make sure the session isn't already in the wishlist
        session_id = session.key.id()
        profile = self._getProfileFromUser()
        if session_key.urlsafe() in profile.wishlistSessionKeys:
            raise endpoints.BadRequestException("Session already in wishlist.")

        profile.wishlistSessionKeys.append(session_key.urlsafe())
        profile.put()

        # return the updated profile
        return self._copyProfileToForm(profile)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='profile/wishlist',
            http_method='GET',
            name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Return the sessions in the user's wishlist.
        """
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get the user's profile
        profile = self._getProfileFromUser()
        sessionForms = []
        for websafe_key in profile.wishlistSessionKeys:
            key = ndb.Key(urlsafe=websafe_key)
            session = key.get()
            if session:
                sessionForms.append(self._copySessionToForm(session))

        # return set of ConferenceForm objects per Conference
        return SessionForms(items=sessionForms)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")



# - - - Featured Speaker - - - - - - - - - - - - - - - - - - - -

    def cacheFeaturedSpeaker(self, speaker, sessions):
        """Create announcement about a featured speaker & assign to
        memcache; used by memcache cron job &
        setFeaturedSpeakerHandler().
        """
        if speaker:
            conference = sessions[0].key.parent().get()

            text = '{S} is speaking a bunch at the {C} conference!' \
                   .format(S=speaker.displayName, C=conference.name)
            for session in sessions:
                text += ' {S}!'.format(S=session.name)
            memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, text)
        else:
            # NOTE: we're never clearing the cache. Should probably
            # do that after the conference is over...chron job...?
            text = ""
            memcache.delete(MEMCACHE_FEATURED_SPEAKER_KEY)

        return text


    @endpoints.method(message_types.VoidMessage, StringMessage,
        path='conference/featuredspeaker/get',
        http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return Featured Speaker from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


api = endpoints.api_server([ConferenceApi]) # register API
