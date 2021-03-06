"""
Edit testing for V1 of API
"""
from flask import json, jsonify

from app import db
from app.api.data import any_existing_rows
from app.models.data import *
from common import *
import datetime


def test_edit_core_data(app, headers, slack_mock):
    client = app.test_client()

    # Write a batch containing the above data, two days for NY and WA, publish it
    resp = client.post(
        "/api/v1/batches",
        data=json.dumps(daily_push_ny_wa_two_days()),
        content_type='application/json',
        headers=headers)
    assert resp.status_code == 201
    batch_id = resp.json['batch']['batchId']
    assert slack_mock.chat_postMessage.call_count == 1

    # Publish the new batch
    resp = client.post("/api/v1/batches/{}/publish".format(batch_id), headers=headers)
    assert resp.status_code == 201
    assert slack_mock.chat_postMessage.call_count == 2

    # make an edit batch for NY for yesterday
    resp = client.post(
        "/api/v1/batches/edit",
        data=json.dumps(edit_push_ny_yesterday()),
        content_type='application/json',
        headers=headers)
    assert resp.status_code == 201
    assert slack_mock.chat_postMessage.call_count == 3
    batch_id = resp.json['batch']['batchId']
    assert resp.json['batch']['user'] == 'testing'

    # test that getting the states daily for NY has the UNEDITED data for yesterday
    resp = client.get("/api/v1/public/states/NY/daily")
    assert len(resp.json) == 2
    unedited = resp.json

    for day_data in resp.json:
        assert day_data['date'] in ['2020-05-25', '2020-05-24']
        if day_data['date'] == '2020-05-25':
            assert day_data['positive'] == 20
            assert day_data['negative'] == 5
        elif day_data['date'] == '2020-05-24':
            assert day_data['positive'] == 15
            assert day_data['negative'] == 4

    # Publish the edit batch
    resp = client.post("/api/v1/batches/{}/publish".format(batch_id), headers=headers)
    assert resp.status_code == 201

    # test that getting the states daily for NY has the edited data for yesterday
    resp = client.get("/api/v1/public/states/NY/daily")
    assert len(resp.json) == 2

    for day_data in resp.json:
        assert day_data['date'] in ['2020-05-25', '2020-05-24']
        if day_data['date'] == '2020-05-25':
            assert day_data['positive'] == 20
            assert day_data['negative'] == 5
        elif day_data['date'] == '2020-05-24':
            assert day_data['positive'] == 16
            assert day_data['negative'] == 4


def test_edit_core_data_from_states_daily(app, headers, slack_mock):
    client = app.test_client()

    # Write a batch containing the above data, two days for NY and WA, publish it
    resp = client.post(
        "/api/v1/batches",
        data=json.dumps(daily_push_ny_wa_two_days()),
        content_type='application/json',
        headers=headers)
    assert resp.status_code == 201
    batch_id = resp.json['batch']['batchId']
    assert slack_mock.chat_postMessage.call_count == 1

    # Publish the new batch
    resp = client.post("/api/v1/batches/{}/publish".format(batch_id), headers=headers)
    assert resp.status_code == 201
    assert slack_mock.chat_postMessage.call_count == 2

    # make an edit batch for NY for yesterday, and leave today alone
    resp = client.post(
        "/api/v1/batches/edit_states_daily",
        data=json.dumps(edit_push_ny_yesterday_unchanged_today()),
        content_type='application/json',
        headers=headers)
    assert resp.status_code == 201
    assert slack_mock.chat_postMessage.call_count == 3
    assert "state: NY" in slack_mock.chat_postMessage.call_args[1]['text']
    batch_id = resp.json['batch']['batchId']
    assert resp.json['batch']['user'] == 'testing'
    # we've changed positive and removed inIcuCurrently, so both should count as changed
    assert len(resp.json['changedFields']) == 2
    assert 'positive' in resp.json['changedFields']
    assert 'inIcuCurrently' in resp.json['changedFields']
    assert resp.json['changedDates'] == '5/24/20'

    # confirm that the edit batch only contains one row with yesterday's data
    with app.app_context():
        batch_obj = Batch.query.get(batch_id)
        assert len(batch_obj.coreData) == 1
        assert batch_obj.coreData[0].date == datetime.date(2020,5,24)
        assert batch_obj.coreData[0].state == 'NY'
        assert batch_obj.link == 'https://example.com'
        assert batch_obj.user == 'testing'
        assert batch_obj.logCategory == 'State Updates'

    # getting the states daily for NY has the edited data for yesterday and unchanged for today,
    # and the last batch should've been published as part of the "edit from states daily" endpoint
    resp = client.get("/api/v1/public/states/NY/daily")
    assert len(resp.json) == 2

    for day_data in resp.json:
        assert day_data['date'] in ['2020-05-25', '2020-05-24']
        if day_data['date'] == '2020-05-25':
            assert day_data['positive'] == 20
            assert day_data['negative'] == 5
            assert day_data['inIcuCurrently'] == 33
        elif day_data['date'] == '2020-05-24':
            assert day_data['positive'] == 16
            assert day_data['negative'] == 4
            # this value was blanked out in the edit, so it should be removed now
            assert 'inIcuCurrently' not in day_data

    # test editing 2 non-consecutive dates
    resp = client.post(
        "/api/v1/batches/edit_states_daily",
        data=json.dumps(edit_push_ny_today_and_before_yesterday()),
        content_type='application/json',
        headers=headers)
    assert resp.json['changedFields'] == ['inIcuCurrently']
    assert resp.json['changedDates'] == '5/20/20 - 5/25/20'
    assert resp.json['numRowsEdited'] == 2
    assert resp.json['user'] == 'testing'

    # check to see if the row for the new date (BEFORE_YESTERDAY) was added
    resp = client.get("/api/v1/public/states/NY/daily")
    found_new_date = False
    for day_data in resp.json:
        if day_data['date'] == '2020-05-20':
            found_new_date = True
            assert day_data['positive'] == 10
            assert day_data['negative'] == 2
    assert found_new_date is True

    # test that sending an edit batch with multiple states fails
    resp = client.post(
        "/api/v1/batches/edit_states_daily",
        data=json.dumps(edit_push_multiple_states()),
        content_type='application/json',
        headers=headers)
    assert resp.status_code == 400

    # test that sending an edit batch with no CoreData rows fails
    bad_data = edit_push_multiple_states()
    bad_data['coreData'] = []
    resp = client.post(
        "/api/v1/batches/edit_states_daily",
        data=json.dumps(bad_data),
        content_type='application/json',
        headers=headers)
    assert resp.status_code == 400


def test_edit_core_data_from_states_daily_timestamps_only(app, headers, slack_mock):
    client = app.test_client()

    # Write a batch containing the above data, two days for NY and WA, publish it
    resp = client.post(
        "/api/v1/batches",
        data=json.dumps(daily_push_ny_wa_two_days()),
        content_type='application/json',
        headers=headers)
    assert resp.status_code == 201
    batch_id = resp.json['batch']['batchId']
    assert slack_mock.chat_postMessage.call_count == 1

    # Publish the new batch
    resp = client.post("/api/v1/batches/{}/publish".format(batch_id), headers=headers)
    assert resp.status_code == 201
    assert slack_mock.chat_postMessage.call_count == 2

    # make an edit batch for NY for yesterday, and leave today alone
    resp = client.post(
        "/api/v1/batches/edit_states_daily",
        data=json.dumps(edit_push_ny_yesterday_change_only_timestamp()),
        content_type='application/json',
        headers=headers)

    assert resp.status_code == 201
    assert slack_mock.chat_postMessage.call_count == 3
    assert "state: NY" in slack_mock.chat_postMessage.call_args[1]['text']
    batch_id = resp.json['batch']['batchId']
    assert resp.json['batch']['user'] == 'testing'
    # we've changed only lastUpdateIsoUtc, which is lastUpdateTime on output
    assert len(resp.json['changedFields']) == 1
    assert 'lastUpdateTime' in resp.json['changedFields']
