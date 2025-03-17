from __future__ import annotations
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
import asyncio
from pathlib import Path
import json
from typing import Optional
from struct import unpack
from collections import namedtuple
from datetime import datetime, timezone
import traceback
import requests
from pprint import pprint
from signal import SIGINT, SIGTERM
from time import time
import threading

# Taken from rapt_ble on github (https://github.com/sairon/rapt-ble/blob/main/src/rapt_ble/parser.py#L14) as well as the decode_rapt_data
RAPTPillMetricsV1 = namedtuple("RAPTPillMetrics", "version, mac, temperature, gravity, x, y, z, battery")
RAPTPillMetricsV2 = namedtuple(
    "RAPTPillMetrics",
    "hasGravityVel, gravityVel, temperature, gravity, x, y, z, battery",
)
PILLS = []
WINDOW = None


class MeadTools(object):
    def __init__(self, data: dict, data_path: Path, pill_holder: PillHolder):
        # filled in by querying MT for it - this is the ispindel id not the hydrometer id
        self.deviceid = data.get("MTDetails", {}).get("MTDeviceToken", None)
        self.pill_holder = pill_holder
        # filled in by querying MT for it
        self.brewid = None
        self.brew_name = ""
        self.data_path = data_path
        self.data = data
        self.hydrometers = []
        self.brews = []
        self.logged_in = False

    @property
    def mt_data(self):
        return self.data.get("MTDetails", {})

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.data['MTDetails'].get('AccessToken', 'ACCESS TOKEN NOT SET')}",
        }

    @property
    def __base_url__(self):
        return self.mt_data.get("MTUrl", "BaseUrlNotSet")

    @property
    def __login_url__(self):
        return f"{self.__base_url__}/auth/login"

    @property
    def __refresh_url__(self):
        return f"{self.__base_url__}/auth/refresh"

    @property
    def __pill_url__(self):
        return f"{self.__base_url__}/hydrometer/rapt-pill"

    @property
    def __hyrdom_url__(self):
        return f"{self.__base_url__}/hydrometer"

    @property
    def __reg_hydrom_url__(self):
        return f"{self.__base_url__}/hydrometer/rapt-pill/register"

    @property
    def __token_url__(self):
        """Url for generating a device token

        Returns:
            str: url to get a token
        """
        return f"{self.__base_url__}/hydrometer/token"

    @property
    def __brews_url__(self):
        return f"{self.__base_url__}/hydrometer/brew"

    def save_data(self):
        """save the self.data back to data.json"""
        self.data_path.chmod(0o777)
        self.data_path.write_text(json.dumps(self.data, indent=4, separators=(",", ": ")))
        print("Saved data!")

    def handle_login(self):
        """Handle logging in or refreshing accessToken

        Raises:
            RuntimeError: Raised when not able to login to MeadTools
        """
        success = False
        if self.mt_data.get("AccessToken", None) and self.mt_data.get("RefreshToken", None):
            success = self.refresh_login()
            if not success:
                print("Refresh Login failed, login again...")
                self.login()
            print(f"Refreshed Login: {success}")

        elif self.mt_data.get("MTEmail", None) and self.mt_data.get("MTPassword", None):
            success = self.login()
        else:
            raise RuntimeError("Not able to login. Check email and password are set in data.json")
        self.logged_in = success

    def refresh_login(self) -> bool:
        """Refresh the access token for the given user

        Returns:
            bool: True if successful, else False
        """
        body = {
            "email": self.mt_data.get("MTEmail", None),
            "refreshToken": self.mt_data.get("RefreshToken", None),
        }
        print("Refreshing login details...")
        response = requests.post(self.__refresh_url__, json=body)
        if response.status_code == 200:
            self.mt_data["AccessToken"] = response.json().get("accessToken")

            self.save_data()
            print("Refreshed login to MeadTools: Successful")
            return True
        else:
            print(f"Failed to Refresh Login! {response}")
            print(f"Attempted with: URL:{self.__refresh_url__} body: {body}")
            return False

    def login(self) -> bool:
        """Attempt to login to MeadTools

        Returns:
            bool: True if success, else False
        """
        body = {
            "email": self.mt_data.get("MTEmail", None),
            "password": self.mt_data.get("MTPassword", None),
        }
        print("Trying to login to MeadTools...")
        response = requests.post(self.__login_url__, json=body)
        if response.status_code == 200:
            self.mt_data["RefreshToken"] = response.json().get("refreshToken")
            self.mt_data["AccessToken"] = response.json().get("accessToken")
            self.save_data()
            print("Logged into MeadTools")
            return True
        else:
            print(f"Failed to Login! {response}")
            print(f"Attempted with: URL: {self.__login_url__} body: {body}")
            return False

    def get_hydrometers(self):
        print(f"Getting Hydrometers from MeadTools: {self.headers} - {self.__hyrdom_url__}")

        response = requests.get(self.__hyrdom_url__, headers=self.headers)
        if response.status_code == 200:
            print(f"Hydrometers: {response.json()}")
            self.hydrometers = response.json().get("devices")
            self.pill_holder.update_status("Successfully got hydrometers from Mead Tools...")
            return True
        else:

            print(f"Failed to get hydrometers! {response}")
            self.pill_holder.update_status(f"Failed to get hydrometers from Mead Tools... Error Code:{response}")
            print(f"Attempted with: URL:{self.__hyrdom_url__} and Auth headers")
            return False

    def register_hydrometer(self, hydrom_name: str):
        """Register a hydrometer for the given device token

        Args:
            hydrom_name (str): name of the hydrometer

        Returns:
            str: hydrometer_token
        """
        body = {"token": self.deviceid, "name": hydrom_name}
        print(f"Registering Hydrometer on MeadTools... Body: {body}  URL:{self.__reg_hydrom_url__}")
        pprint(body, indent=4)
        response = requests.post(self.__reg_hydrom_url__, json=body)
        if response.status_code == 200:
            print("Successfully logged data to MTools...")
            return response.json().get("id", "No Id!")
        else:
            print(f"!!! Failed to register hydrometer! {response} !!!")
            return False

    def get_brews(self):
        print(f"Getting Brews from MeadTools - {self.headers} - {self.__brews_url__}")
        response = requests.get(self.__brews_url__, headers=self.headers)
        if response.status_code == 200:
            print(f"Brews: {response.json()}")
            # should return just a list of brew objects
            self.brews = response.json()
            return True
        else:
            print(f"Failed to get Brews! {response}")
            return False

    def register_brew(self, brew_name: str, hydrom_id: str):
        """Register the brew on MeadTools if it's not already registered

        Returns:
            bool: True if successful else False
        """
        body = {
            "device_id": hydrom_id,
            "brew_name": brew_name,
        }
        print(f"Registering brews with MeadTools : {body}  URL:{self.__brews_url__}")
        response = requests.post(self.__brews_url__, headers=self.headers, json=body)
        print(f"Response: ", response)
        if response.status_code == 200:
            print(f"brews: {response.json()}")
            self.brews = response.json()
            return response.json()

        else:
            print(f"Failed to register brews! {response}")
            raise RuntimeError(f"Couldn't register brew:{brew_name} -  {response}")

    def generate_device_token(self):
        """Generate a new ispindel token - usually we don't want to do this too much - ideally we want the user to fill this
        in the data/gui instead

        Raises:
            RuntimeError: couldn't get a new token

        Returns:
            str: generated token
        """
        print(f"Try to register deviceId... {self.__token_url__} : headers{self.headers}")
        response = requests.post(self.__token_url__, headers=self.headers)
        # this should respond with
        """
        "200": {
            "token": "string - Hydrometer token"
        },
        """

        if response.status_code == 200:
            token = response.json().get("token", "")
            self.deviceid = token
            return token
        else:
            print(f"Failed to register deviceid! {response}")
            self.pill_holder.update_status(f"Couldn't register Pill with MeadTools: {response}")
            raise RuntimeError(f"Couldn't register Pill with MeadTools: {response}")

    def delete_brew(self, brew_data: dict):

        if not brew_data.get("end_date", None):
            print(f"Brew: {brew_data.get('name')} is not ended, can't delete!")
            return False
        brew_id = brew_data.get("id")
        print(f"Trying to delete brew: {self.__brews_url__}/{brew_id}")

        response = requests.delete(f"{self.__brews_url__}/{brew_id}", headers=self.headers)
        print(response)

        if response.status_code == 200:
            print("Deleted brew successfully!")
            return True
        else:
            print("Failed to delete brew!")
            return False

    def link_brew_to_recipe(self, brewid, recipe_id: int):
        body = {"recipe_id": int(recipe_id)}
        print(f"Trying to link brew: {body} - url: {self.__brews_url__}/{self.brewid}")
        response = requests.patch(f"{self.__brews_url__}/{brewid}", headers=self.headers, json=body)
        # this should respond with
        """
        "200": {
            "token": "string - Hydrometer token"
        },
        """
        if response.status_code == 200:
            return response.json().get("MTDeviceId", "")
        else:
            print(f"Failed to link brew:{self.brewid} to recipe:{body.get('recipe_id')}")
            raise RuntimeError(f"Failed to link brew:{self.brewid} to recipe:{body.get('recipe_id')} - {response}")

    def end_brew(self, hyrdometer_token, brew_id):
        if not hyrdometer_token or not brew_id:
            raise RuntimeError(f"Deviced Id: {brew_id}  OR BrewID: {brew_id} Not set correctly, can't end the brew!")
        body = {
            "device_id": hyrdometer_token,
            "brew_id": brew_id,
        }

        print(f"Trying to end brew with {body}")
        response = requests.patch(f"{self.__brews_url__}", headers=self.headers, json=body)
        # this should respond with
        """
        "200": {
            "id": 2,
            "device_id": 3,
            "user_id": 5,
            "brew_name": "Updated Brew Name",
            "start_date": "2024-02-05T10:30:00Z",
            "end_date": null
        }
        """
        if response.status_code == 200:
            print(f"Ended brew: {self.brew_name}")
        else:
            print(f"Failed to end brew -  {response}")

    def ingredients(self):
        """Get the list of ingredients from MeadTools"""
        body = {
            "MTEmail": self.data.get("MTEmail", None),
            "MTPassword": self.data.get("MTPassword", None),
        }
        __login_url__ = f"{self.__base_url__}/ingredients"
        print(__login_url__, body)
        response = requests.get(__login_url__)
        print(response.json())

    def add_data_point(self, pill: RaptPill):
        body = {
            "token": self.deviceid,
            "name": pill.session_data.get("Pill Name", pill.mac_address),
            "gravity": pill.curr_gravity,
            "temperature": pill.temperature,
            "temp_units": pill.temp_unit,
            "battery": pill.battery,
        }
        print(f"Sending data to MeadTools... Body: {body}  URL:{self.__pill_url__}")
        pprint(body, indent=4)
        response = requests.post(self.__pill_url__, json=body)
        if response.status_code == 200:
            print("Successfully logged data to MTools...")
            return True
        else:
            print(f"!!! Failed to log data to MeadTools! {response} !!!")
            return False


class RaptPill(object):
    active_pollers = []

    def __init__(
        self,
        mt_data: dict,
        session_data: dict,
        data_path: Path,
        session_name: str,
        mt_device_id: str,
        mac_address: str,
        poll_interval: int,
        pill_holder: PillHolder,
        log_to_db: bool = True,
        temp_as_celsius: bool = True,
        mtools: MeadTools = None,
    ):
        """Create a Pill object to actively poll for data

        Args:
            session_name (str): name of the session we are tracking
            mac_address (str): address of the pill we are tracking so we know which bluetooth device to watch for
            poll_interval (int): how often should we poll for data in seconds. This ideally will be slightly longer than what is set in the Pill firmware
            mead_tools(MeadTools): details for database to log data to - If None, no data is logged and is just printed to output.
            temp_as_celsius(bool): set False if you want temp as F instead
        """
        # RAPT only lets you put 30 seconds as the lowest temp anyways
        self.min_time = 5
        self.last_time = time()

        self.thread = None
        self.running = False
        self.pill_holder = pill_holder
        # how often should we actively poll for data. This should ideally be slightly longer
        # than the send rate of the PILL so we make sure we are looking while it will be sending
        self.__polling_interval = int(poll_interval)
        # macaddress of pill
        self.__mac_address = mac_address
        # session that will be logged with data
        self.__session_name = session_name
        # device id from iSpindel endpoint on meadtools
        self.__mt_device_id = mt_device_id
        # should be 1 or 2
        self.__api_version = -1
        # temperature value (kelvin)
        self.__temperature = 1
        # C or F
        self.__is_celsius = temp_as_celsius
        self.__gravity_velocity = 0

        # Starting gravity so we can actively know how much abv we have
        self.__starting_gravity = 1.000
        self.__starting_gravity_set = False
        # Current Gravity
        self.__curr_gravity = 1.000
        # abv we have calculated off the start/curr gravity difference
        self.__abv = -1
        # accelerometer data
        self.__x = -100
        self.__y = -100
        self.__z = -100
        # battery life
        self.__battery = 100
        # When was the last event
        self.__last_event = None

        self.mt_data = mt_data
        self.session_data = session_data
        self.data_path = data_path
        self.__log_to_db = log_to_db
        self.mtools = mtools
        if self.__log_to_db:
            self.mtools.handle_login()
            if not self.mtools.logged_in:
                self.pill_holder.update_status("Not Logged in will only print to output...")
                self.__log_to_db = False
            else:
                self.mtools.get_hydrometers()
                self.hydrometer = next(
                    (
                        x
                        for x in self.mtools.hydrometers
                        if x.get("device_name")
                        == self.session_data.get("Pill Name", self.session_data.get("Mac Address", "Default Pill Name"))
                    ),
                    None,
                )
                if self.hydrometer is None:
                    self.hydrometer_token = self.mtools.register_hydrometer(self.session_data.get("Pill Name"))

                else:
                    self.hydrometer_token = self.hydrometer.get("id", "No Hydrom ID!")
                self.initialise_brew()

        # polling variables
        self.__polling_task = None
        self.active_pollers.append(self)
        self.bt_scanner = None

    @property
    def starting_gravity(self) -> float:
        """get the starting gravity as set on first data retrieval
            This is get/set so we can't overwrite it once we're going
        Returns:
            float: gravity value
        """
        return self.__starting_gravity

    @starting_gravity.setter
    def starting_gravity(self, gravity: float):
        """set the starting gravity. This should only be allowed once

        Args:
            gravity (float): value to set as starting gravity
        """
        if self.__starting_gravity_set:
            return
        self.__starting_gravity_set = True
        self.__starting_gravity = gravity

    @property
    def session_name(self) -> str:
        return self.__session_name

    @property
    def gravity_velocity(self) -> float:
        return self.__gravity_velocity

    @property
    def curr_gravity(self):
        return self.__curr_gravity

    @property
    def abv(self):
        return self.__abv

    @property
    def temperature(self):
        return self.__temperature

    @property
    def temp_unit(self):
        return "C" if self.__is_celsius else "F"

    @property
    def battery(self):
        return self.__battery

    @property
    def version(self):
        return self.__api_version

    @property
    def x_accel(self):
        return self.__x

    @property
    def y_accel(self):
        return self.__y

    @property
    def z_accel(self):
        return self.__z

    @property
    def poll_interval(self):
        return self.__polling_interval

    @property
    def last_event(self):
        return self.__last_event

    @property
    def mac_address(self):
        return self.__mac_address

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.start_session, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.thread.join()

    def start_session(self):
        print(f"Starting Session: {self.session_name}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def scan():

            # self.bt_scanner = BleakScanner(detection_callback=self.device_found)
            while self.running:
                # print("Starting BLE scan...")  # ✅ This should print
                async with BleakScanner(self.device_found) as scanner:
                    await asyncio.sleep(self.poll_interval)
                # print("Scan complete. Waiting for next cycle...")
                await asyncio.sleep(10)

        loop.run_until_complete(scan())

    def end_session(self):
        print(f"Stopping thread: {self.session_name}")
        self.running = False
        self.thread = None

        # if self.__polling_task is not None:
        #     self.__polling_task.cancel()
        #     self.__polling_task = None
        #     self.active_pollers.remove(self)
        #     self.mtools.end_brew()
        print(f"Ended Session: {self.session_name}")

    def initialise_brew(self):
        """
        1. Attempt to post to /hydrometer - check if brew_id is set - if not we should have a device_id
         1a. if we have device id but not brew_id - post to /hydrometer/brew with brew name and device_id
        2. Post data blob to /hydrometer which should corrolate to a device and a brew on MT (it handles it)
        """
        device_token = None

        if self.mtools.deviceid == None:
            self.mtools.deviceid = self.mtools.generate_device_token()
            self.mtools.save_data()

        if not self.mtools.deviceid:
            raise ValueError(f"MTDeviceID not set for {self.session_data.get('BrewName')}")

        # try to get all brews
        self.mtools.get_brews()

        if not len(self.mtools.brews):
            # if we have no brews registered, register our brew
            self.mtools.register_brew(self.session_name, self.hydrometer_token)
        else:
            # do some checking of the brews to see if we have one registered already that matches our details
            print(f'Looking for brew: {self.session_data.get("BrewName")}')
            existing_brew = next(
                (
                    x
                    for x in self.mtools.brews
                    if (
                        # Find a matching brew by name
                        x.get("name", "") == self.session_data.get("BrewName")
                        # Find a brew that is still ongoing
                        and x.get("end_date", None) == None
                    )
                ),
                None,
            )
            if not existing_brew:
                print("Couldn't find matching brew name and device_id that is still ongoing... registering new brew!")
                existing_brew = self.mtools.register_brew(self.session_name, self.hydrometer_token)
                self.brewid = existing_brew[0].get("id")
            else:
                print(f"Found existing brew with name: {self.session_data.get('BrewName')} that is ongoing")
                self.brewid = existing_brew.get("id")

        if self.brewid and (
            self.session_data.get("MTRecipeId", "") != "" or self.session_data.get("MTRecipeId", "") != None
        ):
            self.mtools.link_brew_to_recipe(self.brewid, self.session_data.get("MTRecipeId", ""))

    def device_found(self, device: BLEDevice, advertisement_data: AdvertisementData):
        """This is fired everytime the bleakScanner finds a bluetooth device so we check if it is the macaddress of the pill we are tracking
        if it is not, then we ignore it

        Args:
            device (BLEDevice): bluetooth device that was found
            advertisement_data (AdvertisementData): advertisment data from the found bluetooth device
        """
        if device.address.lower() != self.__mac_address.lower():
            return
        # Assuming the custom data is under manufacturer specific data
        raw_data = advertisement_data.manufacturer_data.get(16722, None)
        if raw_data == b"PTdPillG1":
            return
        if raw_data is None:
            return
        self.decode_rapt_data(raw_data)
        print(self)

    def calculate_abv(self, current_gravity: float) -> float:
        """calculate the alchol by volume given the current gravity (we estimate it by calculating against the start gravity we have stored)

        Args:
            current_gravity (float): current gravity value

        Returns:
            float: estimated abv
        """
        return round((self.starting_gravity - current_gravity) * 131.25, 4)

    def calculate_temp(self, kelvin: float) -> float:
        """calculate the temperature from the given kelvin value, return in C or F depending on what we have set as our default

        Args:
            kelvin (float): kelvin temp value

        Returns:
            float: temperature in F or C
        """
        # return in c
        if self.__is_celsius:
            return round(kelvin - 273.15, 2)
        # return in f
        return (kelvin - 273.15) * (9 / 5) + 32

    def decode_rapt_data(self, data: bytes):
        """Given bytes from a bluetooth advertisement, decode it into the RAPTPillMetrics tuple and return it so it can be used.
        Updates class values
        Args:
            data (bytes): advertisement data as bytes

        Raises:
            ValueError: length of data isn't correct

        """
        if len(data) != 23:
            raise ValueError("advertisment data must have length 23")

        # print(f"===> raw_data: {data}")

        # Extract and check the version
        prefix, version = unpack(">2sB", data[:3])
        # Validate the prefix
        if prefix != b"PT":
            raise ValueError("Unexpected prefix")
        # get "raw" data, drop second part of the prefix ("PT"), start with the version
        if version == 1:
            metrics_raw = RAPTPillMetricsV1._make(unpack(">B6sHfhhhh", data[2:]))
        else:
            metrics_raw = RAPTPillMetricsV2._make(unpack(">BfHfhhhH", data[4:]))

        now = datetime.now(timezone.utc)
        dt_string = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        # print("date and time =", dt_string)
        if not self.__starting_gravity_set:
            self.starting_gravity = round(metrics_raw.gravity / 1000, 4)
        self.__api_version = version
        self.__gravity_velocity = metrics_raw.gravityVel
        self.__curr_gravity = round(metrics_raw.gravity / 1000, 4)
        self.__abv = self.calculate_abv(self.__curr_gravity)
        self.__temperature = self.calculate_temp(metrics_raw.temperature / 128)
        self.__battery = round(metrics_raw.battery / 256)
        self.__last_event = dt_string
        self.__x = metrics_raw.x / 16
        self.__y = metrics_raw.y / 16
        self.__z = metrics_raw.z / 16

        if self.__log_to_db:
            curr_time = time()
            time_since = curr_time - self.last_time
            if time_since >= self.min_time:
                self.last_time = curr_time

                self.mtools.add_data_point(self)
                self.pill_holder.update_status(
                    f"Logged Data to MeadTools for: {self.session_name} - SG:{self.curr_gravity} , Temp: {self.temperature} , ~ABV:{self.abv}"
                )
        else:
            curr_time = time()
            time_since = curr_time - self.last_time
            if time_since >= self.min_time:
                self.last_time = curr_time

                print(self)
                print("Logging to console only")

    def __repr__(self):
        return (
            "Current Data: \n"
            f"BrewName: {self.__session_name} , "
            "\n"
            f"Firmware Version: {self.version}, "
            "\n"
            f"MacAddr: {self.__mac_address} , "
            "\n"
            f"Start Gravity: {self.__starting_gravity} , "
            "\n"
            f"CurrGravity: {self.__curr_gravity} , "
            "\n"
            f"ABV: {self.__abv} , "
            "\n"
            f"Last Event TimeStamp:{self.__last_event}"
            "\n"
            f"Temp: {self.__temperature} {'f' if not self.__is_celsius else 'c'}, "
            "\n"
            f"X-Accel : {self.__x} , "
            "\n"
            f"Y-Accel : {self.__y} , "
            "\n"
            f"Z-Accel : {self.__z} , "
            "\n"
            f"Battery : {self.__battery} , "
        )


class PillHolder(object):
    def __init__(self):
        self.curr_dir = Path(__file__).parent
        self.data_path = self.curr_dir.joinpath("data.json")
        self.pills = []
        self.ui = None

        # if data is filled in data.json file use it and start sessions and database (if set)
        if not self.data_path.exists():
            raise RuntimeError("data.json file is missing, can't start!")

        # Read data.json and spin up processes
        self.data = json.loads(self.data_path.read_text())
        self.mtools = MeadTools(self.data, self.data_path, self)
        if not self.data.get("Sessions", []):
            self.data["Sessions"] = []
        self.mtools.save_data()

        if self.data.get("UseGui", True):
            global WINDOW
            import PillGui

            PillGui.setup_ui(self)
            WINDOW = PillGui.WINDOW
            self.ui = WINDOW
            if WINDOW:

                WINDOW.qapp.exec()

            else:
                raise RuntimeError("data.json not found! - refer to github depot on how to get/setup data.json")
        else:
            raise RuntimeError("Can't currently run without gui!")

    def run_pills(self):
        print("Starting Pill Sessions...")
        for pill_details in self.data.get("Sessions", []):
            # MAC addresses of your RAPT Pill(s) - in case you have more (This hasn't been actually tested but it should in theory work.)
            print(pill_details)

            pill = RaptPill(
                self.data,
                pill_details,
                self.data_path,
                pill_details.get("BrewName", "NoSessionNameSet"),
                self.data.get("MTDetails", {}).get("MTDeviceToken", "NO DEVICE ID"),
                pill_details.get("Mac Address", "No Mac Address Set!"),
                pill_details.get("Poll Interval", ""),
                pill_holder=self,
                temp_as_celsius=pill_details.get("Temp in C", True),
                mtools=self.mtools,
            )
            self.pills.append(pill)
            if pill.mtools.logged_in:
                print("Should start pill session!")
                pill.start()

            else:
                self.update_status(f"Not logged in to MeadTools - can't start Brew: {pill.session_name}")

    def run_pill(self, pill_details: dict):
        print(f"Running single pill: {pill_details.get('Session Name')}")
        pill = RaptPill(
            self.data,
            pill_details,
            self.data_path,
            pill_details.get("BrewName", "NoSessionNameSet"),
            self.data.get("MTDetails", {}).get("MTDeviceToken", "NO DEVICE ID"),
            pill_details.get("Mac Address", "No Mac Address Set!"),
            pill_details.get("Poll Interval", ""),
            pill_holder=self,
            temp_as_celsius=pill_details.get("Temp in C", True),
            mtools=self.mtools,
        )
        self.pills.append(pill)
        if pill.mtools.logged_in:
            print("Should start pill session!")
            pill.start()

        else:
            self.update_status(f"Not logged in to MeadTools - can't start Brew: {pill.session_name}")

    def stop_pill(self, pill_details: dict):
        """Stop the pill monitoring if we can find a matching pill

        Args:
            pill_details (dict): dict of pill details
        """
        pill = next((x for x in self.pills if x.session_name == pill_details.get("BrewName")), None)
        if pill:
            pill.end_session()
            self.pills.remove(pill)
        else:
            self.update_status(f"Couldn't find matching pill data for: {pill.data.get('BrewName')}")

    def update_status(self, message: str):
        """update the status bar in the gui

        Args:
            message (str): message to show
        """
        if not self.ui:
            print(message)
            return
        self.ui.update_status(message)


def main() -> None:
    # Handle setup of database and pill(s)
    pillHolder = PillHolder()


if __name__ == "__main__":
    main()
