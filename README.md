# RaptPill To MeadTools
Using a RAPT Pill tracker, collect the bluetooth data and log it to MeadTools.com

# Requirements
Python 3.9+
Install requirements.txt (python -m pip install -r requirements.txt)



# Steps To Use
Make sure reqs are installed and then open the src/data.json in a text editor. 
See below section about what to fill in 
run it - 
python src/PillToMeadTools.py

This should give you a gui that you can login to Mead Tools with and start tracking a brew
Currently it's setup to only work with a gui, but future updates will allow you to do it headless.

It also might be buggy and is advised to run with a shell/command prompt so you can see output

If you have a token from https://meadtools.com/account/hydrometer/setup you can fill that in the iSpindel Device Token section of the brew information, else login and then hit generate token. This shouldn't need to be done per pill, as they should all share the same token.

Fill in your Pill Name (e.g. Yellow Top, Red Top etc. or whatever you want to call it)


If you have a recipe ID you want to link the session with, enter it - it should be a number


Set a brew name that you want to use


Set the  Mac Address of your Pill - found when you connect to it in the diagnostics page. You need to add 2 to the last set of digits e.g if the MAC address is 11-e3-1d-19-14 the address you put in the data.json is 11-e3-1d-19-16 


Poll interval is how long it will look for bluetooth data before stopping for another 10 seconds. 

When filling in these text boxes, please make sure to hit Enter to save it, else it will only save when you start a session.

# Steps To Use
Make sure reqs are installed and then open the src/data.json in a text editor. 
See below section about what to fill in 
run it - python src/PillToMeadTools.py

# data.json explanation
With current version you shouldn't need to fill this in.
In MTDetails section Fill in the following:
"MTEmail": "YourAccountEmail"
"MTPassword": "YourAccountPassword"

# Sessions
For each Rapt Pill:

"MTDeviceToken" - If you have setup a device on MeadTools already, you can set this here or we will set one up

"MTRecipeId" - If you have a recipe on MeadTools you want this data to be linked to, you want the numbers at the end of the recipe URl (e.g. https://meadtools.com/recipes/70 - 70 is the ID)

"BrewName": - A name you want to set in MeadTools for the Brew Name

"Mac Address": - Mac Address of your Pill - found when you connect to it in the diagnostics page. You need to add 2 to the  
                last set of digits e.g if the MAC address is 11-e3-1d-19-14 the address you put in the data.json is 11-e3-1d-19-16 

"Poll Interval" - seconds to poll for before resting

"Temp in C": true if you want temp in c else it will be in F

"Log To Database": if true, log to MeadTools else just print in window/console



