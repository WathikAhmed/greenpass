#!/usr/bin/env python3

# Green Pass Parser
# Copyright (C) 2021  Davide Berardi -- <berardi.dav@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import re
import os
import sys
import pickle
import pytz
import json
import requests
from datetime import datetime
from tzlocal import get_localzone

from greenpass.URLs import *

# Retrieve settings from unified API endpoint
class SettingsManager(object):
    def __init__(self, cachedir=''):
        self.at_date = None
        self.cachedir = cachedir
        self.blocklist = set()
        if cachedir != '':
            self.get_cached_settings()
        else:
            self.get_settings()

    def get_cached_settings(self):
        settings = os.path.join(self.cachedir, "settings")

        os.makedirs(self.cachedir, exist_ok=True)

        if not os.path.exists(settings):
            with open(settings, 'wb') as f:
                pickle.dump(self.get_settings(), f)

        with open(settings, 'rb') as f:
            self.vaccines, self.recovery, self.test, self.blocklist = pickle.load(f)

    def get_settings(self):
        r = requests.get("{}/settings".format(BASE_URL_DGC))
        if r.status_code!=200:
            print("[-] Error from API")
            sys.exit(1)

        self.vaccines = {}
        self.recovery = {}
        self.test    = {
            "molecular": {},
            "rapid": {}
        }

        settings = json.loads(r.text)
        # Dispatch and create the dicts
        for el in settings:
            if "vaccine" in el["name"]:
                if self.vaccines.get(el["type"], None) == None:
                    self.vaccines[el["type"]] = {
                        "complete": {
                            "start_day": -1,
                            "end_day": -1
                        },
                        "not_complete": {
                            "start_day": -1,
                            "end_day": -1
                        }
                    }
                if "not_complete" in el["name"]:
                    vtype = "not_complete"
                elif "complete" in el["name"]:
                    vtype = "complete"

                if "start_day" in el["name"]:
                    daytype = "start_day"
                elif "end_day" in el["name"]:
                    daytype = "end_day"

                self.vaccines[el["type"]][vtype][daytype] = int(el["value"])

            elif "recovery" in el["name"]:
                if "start_day" in el["name"]:
                    self.recovery["start_day"] = int(el["value"])
                elif "end_day" in el["name"]:
                    self.recovery["end_day"] = int(el["value"])

            elif "test" in el["name"]:
                if "molecular" in el["name"]:
                    ttype = "molecular"
                elif "rapid" in el["name"]:
                    ttype = "rapid"

                if "start_hours" in el["name"]:
                    hourtype = "start_hours"
                elif "end_hours" in el["name"]:
                    hourtype = "end_hours"

                self.test[ttype][hourtype] = int(el["value"])
            elif "ios" == el["name"] or "android" == el["name"]:
                # Ignore app specific options
                pass
            elif "black_list_uvci" == el["name"]:
                self.blocklist = self.blocklist.union( set(el["value"].split(";")[:-1]) )
            else:
                print("[~] Unknown field {}".format(el["name"]))
        return self.vaccines, self.recovery, self.test, self.blocklist

    # Return the time that a test is still valid, negative time if expired
    def get_test_remaining_time(self, test_date, ttype):
        hours = self.test.get(ttype, 0)

        try:
            seconds_since_test = (self.checktime() - test_date).total_seconds()
            hours_since_test = seconds_since_test / (60 * 60)
        except Exception as e:
            print(e, file=sys.stderr)
            return 0,0

        valid_start = (hours_since_test - hours["start_hours"])
        valid_end   = (hours["end_hours"] - hours_since_test)

        return valid_start, valid_end

    # Return the time that a vaccine is still valid, negative
    # time if expired
    def get_vaccine_remaining_time(self, vaccination_date, vtype, full):
        if full:
            selector = "complete"
        else:
            selector = "not_complete"

        days = self.vaccines.get(vtype, { "complete": 0, "not_complete": 0})[selector]

        try:
            seconds_since_vaccine = (self.checktime() - vaccination_date).total_seconds()
            hours_since_vaccine = seconds_since_vaccine / (60 * 60)
        except Exception as e:
            print(e, file=sys.stderr)
            return 0,0

        valid_start = (hours_since_vaccine - days["start_day"] * 24)
        valid_end   = (days["end_day"] * 24 - hours_since_vaccine)

        return int(valid_start), int(valid_end)

    # Return the time that a recovery certification is still valid, negative
    # time if expired
    def get_recovery_remaining_time(self, recovery_from, recovery_until):
        days = self.recovery

        try:
            seconds_since_recovery = (self.checktime() - recovery_from).total_seconds()
            hours_since_recovery = seconds_since_recovery / (60 * 60)
        except Exception as e:
            print(e, file=sys.stderr)
            return 0,0

        valid_start = (hours_since_recovery - days["start_day"] * 24)
        valid_end   = (days["end_day"] * 24 - hours_since_recovery)

        valid_until = (recovery_until - self.checktime()).total_seconds()
        valid_until = valid_until / (60 * 60)

        valid_end = min(valid_end, valid_until)

        return int(valid_start), int(valid_end)

    def get_blocklist(self):
        return self.blocklist

    def check_uvci_blocklisted(self, uvci):
        return uvci in self.blocklist

    def checktime(self):
        if self.at_date == None:
            d = datetime.now(pytz.utc)
        else:
            d = self.at_date
        return d

    def set_at_date(self, at_date):
        tz = get_localzone()
        # Sanity check to see which are the value inputted
        # Date time, seconds and timezone
        if re.match(r"\d{4}-\d{2}-\d{2}-\d{2}:\d{2}:\d{2}[+-][:0-9]{2,4}", at_date):
            self.at_date = datetime.strptime(at_date, "%Y-%m-%d-%H:%M:%S%z")
        # Date, time and timezone
        elif re.match(r"\d{4}-\d{2}-\d{2}-\d{2}:\d{2}[+-][:0-9]{2,4}", at_date):
            self.at_date = datetime.strptime(at_date, "%Y-%m-%d-%H:%M%z")
        # Date time and seconds
        elif re.match(r"\d{4}-\d{2}-\d{2}-\d{2}:\d{2}:\d{2}", at_date):
            self.at_date = datetime.strptime(at_date, "%Y-%m-%d-%H:%M:%S")
            self.at_date = self.at_date.replace(tzinfo=tz)
        # Date and time
        elif re.match(r"\d{4}-\d{2}-\d{2}-\d{2}:\d{2}", at_date):
            self.at_date = datetime.strptime(at_date, "%Y-%m-%d-%H:%M")
            self.at_date = self.at_date.replace(tzinfo=tz)
        # Only the date
        elif   re.match(r"\d{4}-\d{2}-\d{2}", at_date):
            self.at_date = datetime.strptime(at_date, "%Y-%m-%d")
            self.at_date = self.at_date.replace(tzinfo=tz)
        else:
            print("[-] Unrecognized time format {}".format(at_date))
            sys.exit(1)
