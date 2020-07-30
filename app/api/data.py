"""Registers the necessary routes for the core data model. """

from datetime import datetime

import flask
from flask import render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
import pandas as pd
from sqlalchemy import func, and_

from app import db
from app.api import api
from app.api.common import states_daily_query
from app.models.data import *
from app.utils.slacknotifier import notify_slack, notify_slack_error, exceptions_to_slack
from app.utils.validation import validate_core_data_payload, validate_edit_data_payload
from app.utils.webhook import notify_webhook


##############################################################################################
######################################   Health check      ###################################
##############################################################################################


@api.route('/test', methods=['GET'])
def get_data():
    flask.current_app.logger.info('Retrieving all data: placeholder')
    flask.current_app.logger.debug('This is a debug log')
    return flask.jsonify({'test_data_key': 'test_data_value'})


@api.route('/test_auth', methods=['GET'])
@jwt_required
def test_auth():
    return flask.jsonify({'user': 'authenticated'}),200

##############################################################################################
######################################   Batches      ########################################
##############################################################################################


@api.route('/batches', methods=['GET'])
def get_batches():
    flask.current_app.logger.info('Retrieving all batches')
    batches = Batch.query.all()
    # for each batch, attach its coreData rows
    
    return flask.jsonify({
        'batches': [batch.to_dict() for batch in batches]
    })


@api.route('/batches/<int:id>', methods=['GET'])
def get_batch_by_id(id):
    batch = Batch.query.get_or_404(id)
    flask.current_app.logger.info('Returning batch %d' % id)
    return flask.jsonify(batch.to_dict())


@api.route('/batches/<int:id>/publish', methods=['POST'])
@jwt_required
@exceptions_to_slack
def publish_batch(id):
    flask.current_app.logger.info('Received request to publish batch %d' % id)
    batch = Batch.query.get_or_404(id)

    # if batch is already published, fail out
    if batch.isPublished:
        return flask.jsonify('Batch %d already published, rejecting double-publish' % id), 422

    batch.isPublished = True
    batch.publishedAt = datetime.utcnow()   # set publish time to now
    db.session.add(batch)
    db.session.commit()

    notify_webhook()

    notify_slack(f"*Published batch #{id}* (type: {batch.dataEntryType})\n"
                 f"{batch.batchNote}")

    return flask.jsonify(batch.to_dict()), 201


##############################################################################################
######################################   Core data      ######################################
##############################################################################################

# Expects a dictionary of push context, state info, and core data rows. Writes to DB.
def post_core_data_json(payload):
    # test the input data
    try:
        validate_core_data_payload(payload)
    except ValueError as e:
        notify_slack_error(str(e), 'post_core_data_json')
        return flask.jsonify(str(e)), 400

    # we construct the batch from the push context
    context = payload['context']
    flask.current_app.logger.info('Creating new batch from context: %s' % context)
    batch = Batch(**context)
    batch.user = get_jwt_identity()
    db.session.add(batch)
    db.session.flush()  # this sets the batch ID, which we need for corresponding coreData objects

    # add states
    state_dicts = payload['states']
    state_objects = []
    for state_dict in state_dicts: 
        state_pk = state_dict['state']
        if db.session.query(State).get(state_pk) is not None:
            flask.current_app.logger.info('Updating state row from info: %s' % state_dict)
            db.session.query(State).filter_by(state=state_pk).update(state_dict)
            state_objects.append(db.session.query(State).get(state_pk))  # return updated state
        else:
            flask.current_app.logger.info('Creating new state row from info: %s' % state_dict)
            state = State(**state_dict)
            db.session.add(state)
            state_objects.append(state)

        db.session.flush()

    # add all core data rows
    core_data_dicts = payload['coreData']
    core_data_objects = []
    for core_data_dict in core_data_dicts:
        flask.current_app.logger.info('Creating new core data row: %s' % core_data_dict)
        core_data_dict['batchId'] = batch.batchId
        core_data = CoreData(**core_data_dict)
        db.session.add(core_data)
        core_data_objects.append(core_data)

    db.session.flush()

    # construct the JSON before committing the session, since sqlalchemy objects behave weirdly
    # once the session has been committed
    json_to_return = {
        'batch': batch.to_dict(),
        'coreData': [core_data.to_dict() for core_data in core_data_objects],
        'states': [state.to_dict() for state in state_objects],
    }

    db.session.commit()

    # this returns a tuple of flask response and status code: (flask.Response, int)
    return flask.jsonify(json_to_return), 201


@api.route('/batches', methods=['POST'])
@jwt_required
@exceptions_to_slack
def post_core_data():
    """
    Workhorse POST method for core data

    Requirements: 
    """
    flask.current_app.logger.info('Received a CoreData write request')
    payload = flask.request.json  # this is a dict

    post_result = post_core_data_json(payload)
    status_code = post_result[1]
    if status_code == 201:
        batch_info = post_result[0].json['batch']
        notify_slack(f"*Pushed batch #{batch_info['batchId']}* (type: {batch_info['dataEntryType']}, user: {batch_info['shiftLead']})\n"
                     f"{batch_info['batchNote']}")

    return post_result

def any_existing_rows(state, date):
    date = CoreData.parse_str_to_date(date)
    existing_rows = db.session.query(CoreData).join(Batch).filter(
        Batch.isPublished == True,
        CoreData.state == state,
        CoreData.date == date).all()
    return len(existing_rows) > 0

# Returns a string with any errors if the payload is invalid, otherwise returns empty string.
def edit_data_payload_error(payload):
    # check push context
    if 'context' not in payload:
        return "Payload requires 'context' field"
    if payload['context']['dataEntryType'] != 'edit':
        return "Payload 'context' must contain data entry type 'edit'"
    if not payload['context'].get('batchNote'):
        return "Payload 'context' must contain a batchNote explaining edit"

    # check that edit data exists
    if 'coreData' not in payload:
        return "Payload requires 'coreData' field"

    return ''

@api.route('/batches/edit', methods=['POST'])
@jwt_required
@exceptions_to_slack
def edit_core_data():
    flask.current_app.logger.info('Received a CoreData edit request')
    payload = flask.request.json

    # test input data
    try:
        validate_edit_data_payload(payload)
    except ValueError as e:
        notify_slack_error(str(e), 'edit_core_data')
        return flask.jsonify(str(e)), 400

    # we construct the batch from the push context
    context = payload['context']
    flask.current_app.logger.info('Creating new batch from context: %s' % context)
    batch = Batch(**context)
    batch.user = get_jwt_identity()
    batch.isRevision = True
    db.session.add(batch)
    db.session.flush()  # this sets the batch ID, which we need for corresponding coreData objects

    # check each core data row that the corresponding date/state already exists in published form
    core_data_dicts = payload['coreData']
    core_data_objects = []
    for core_data_dict in core_data_dicts:
        flask.current_app.logger.info('Creating new core data row: %s' % core_data_dict)

        # check that there exists at least one published row for this date/state
        date = core_data_dict['date']
        state = core_data_dict['state']
        if not any_existing_rows(state, date):
            return flask.jsonify("No existing published row for state %s on date %s" % (
                state, date)), 400

        core_data_dict['batchId'] = batch.batchId
        core_data = CoreData(**core_data_dict)
        db.session.add(core_data)
        core_data_objects.append(core_data)

    db.session.flush()

    json_to_return = {
        'batch': batch.to_dict(),
        'coreData': [core_data.to_dict() for core_data in core_data_objects],
    }

    db.session.commit()

    notify_slack(
        f"*Pushed batch #{batch.batchId}* (type: {batch.dataEntryType}, user: {batch.shiftLead})\n"
        f"{batch.batchNote}")

    return flask.jsonify(json_to_return), 201

@api.route('/batches/edit_states_daily', methods=['POST'])
@jwt_required
@exceptions_to_slack
def edit_core_data_from_states_daily():
    flask.current_app.logger.info('Received a CoreData States Daily edit request')
    payload = flask.request.json

    # test input data
    try:
        validate_edit_data_payload(payload)
    except ValueError as e:
        notify_slack_error(str(e), 'edit_core_data_from_states_daily')
        return flask.jsonify(str(e)), 400

    # we construct the batch from the push context
    context = payload['context']

    # check that the state is set
    state_to_edit = context.get('state')
    if not state_to_edit:
        notify_slack_error(
            'No state specified in batch edit context', 'edit_core_data_from_states_daily')
        return flask.jsonify('No state specified in batch edit context'), 400

    flask.current_app.logger.info('Creating new batch from context: %s' % context)
    batch = Batch(**context)
    batch.user = get_jwt_identity()
    batch.isRevision = True
    batch.isPublished = True  # edit batches are published by default
    batch.publishedAt = datetime.utcnow()
    db.session.add(batch)
    db.session.flush()  # this sets the batch ID, which we need for corresponding coreData objects

    latest_daily_data_for_state = states_daily_query(state=state_to_edit).all()

    # split up by date for easier lookup/comparison with input edit rows
    date_to_data = {}
    for state_daily_data in latest_daily_data_for_state:
        date_to_data[state_daily_data.date] = state_daily_data

    # check each core data row that the corresponding date/state already exists in published form
    core_data_dicts = payload['coreData']
    core_data_objects = []
    for core_data_dict in core_data_dicts:
        # this state has to be identical to the state from the context
        state = core_data_dict['state']
        if state != state_to_edit:
            error = 'Context state %s does not match JSON data state %s' % (state_to_edit, state)
            notify_slack_error(error, 'edit_core_data_from_states_daily')
            return flask.jsonify(error), 400
        
        # is there a date for this?
        # check that there exists at least one published row for this date/state
        date = CoreData.parse_str_to_date(core_data_dict['date'])
        data_for_date = date_to_data.get(date)

        # check all numeric and States Grades rows in existing data vs edit data
        any_different = False
        fields_to_check = CoreData.numeric_fields().copy()
        fields_to_check.append('dataQualityGrade')

        if not data_for_date:
            # TODO: uncomment these 3 lines if we want to enforce editing only existing date rows
            # error = 'Attempting to edit a nonexistent date: %s' % core_data_dict['date']
            # flask.current_app.logger.error(error)
            # return flask.jsonify(error), 400

            # right now, this situation will by default be treated as a change
            flask.current_app.logger.info('Row for date not found: %s' % date)
            any_different = True

        else:
            for field in fields_to_check:
                if getattr(data_for_date, field) != core_data_dict.get(field):
                    any_different = True
                    break

        # if any value in the row is different, make an edit batch
        if any_different:
            core_data_dict['batchId'] = batch.batchId
            core_data = CoreData(**core_data_dict)
            db.session.add(core_data)
            core_data_objects.append(core_data)
            flask.current_app.logger.info('Change detected in row: %s' % core_data_dict)
        else:
            flask.current_app.logger.info('All values are the same for date %s, ignoring' % date)

    db.session.flush()

    json_to_return = {
        'batch': batch.to_dict(),
        'coreData': [core_data.to_dict() for core_data in core_data_objects],
    }

    db.session.commit()
    notify_slack(
        f"*Pushed edit batch #{batch.batchId}* (user: {batch.shiftLead})\n"
        f"{batch.batchNote}")

    return flask.jsonify(json_to_return), 201


def list_history_for_state_and_date(state, date):
    return db.session.query(CoreData).join(Batch).filter(
        Batch.isPublished == True,
        CoreData.state == state,
        CoreData.date == date
        ).order_by(CoreData.batchId.desc()).all()


@api.route('/public/state-date-history/<string:state>/<string:date>', methods=['GET'])
def get_state_date_history(state, date):
    flask.current_app.logger.info('Retrieving state date history')

    rows = list_history_for_state_and_date(state.upper(), date)
    row_dicts = pd.DataFrame(x.to_dict() for x in rows).to_dict('records')
    for idx, row in enumerate(row_dicts):  # copy in the associated batch data
        row['batch'] = rows[idx].batch

    return render_template(
        'state_date_history.html',
        title='State Date History',
        state=state,
        date=date,
        data=row_dicts)
