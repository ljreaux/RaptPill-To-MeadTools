# RaptPill To MeadTools
Using a RAPT Pill tracker, collect the bluetooth data and log it to MeadTools.com



# data.json explanation

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