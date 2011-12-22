# Create your views here.
from django.http import HttpResponse
import datetime
import sbhs
import hashlib
import json
import datetime
import time
import os

from sbhshw.models import SlotBooking, Account

from django.views.decorators.csrf import csrf_exempt                                          

# HTML RESPONSE FORMAT :
# 1: STATUS / DATA : S/D
# 2: SUCCESS / FAILED : 1/0
# 3: MESSAGE : MESSAGE STRING

log_file_path = "/home/cdeep/LOG/"

def checkconnection(request):
    """ test connection """
    return HttpResponse("TESTOK")

@csrf_exempt
def startexp(request):
    """ start experiment for authenticated users """
    if request.method == "POST":
        cur_dt = datetime.datetime.now()
        exp_diff_ts = 0

        rollno = request.POST.get('rollno', None)
        password = request.POST.get('password', None)
        # check if username and password is present
        if not rollno or not password:
            html = json.dumps(['S', '0', 'Please provide username and password'])
            return HttpResponse(html)

        # authenticate user
        password = hashlib.md5(password).hexdigest()
        user = Account.objects.filter(
            rollno = rollno,
            password = password,
        )
        if not user:
            html = json.dumps(['S', '0', 'Authentication failed'])
            return HttpResponse(html)
        else:
            user = user[0]

        # check the slot booking for user for current date
        booking = SlotBooking.objects.filter(
            rollno = rollno,
            slot_date = cur_dt.strftime("%d/%m/%Y"),    # current date
        )
        # check if booking found
        if booking:
            cur_booking = False
            # loop through each booking and check the start and end time
            for temp_booking in booking:
                try:
                    temp_start_h, temp_start_m = temp_booking.start_time.split('.')
                    temp_end_h, temp_end_m = temp_booking.end_time.split('.')
                    temp_start_h = int(temp_start_h)
                    temp_start_m = int(temp_start_m)
                    temp_end_h = int(temp_end_h)
                    temp_end_m = int(temp_end_m)
                    ts_check = False
                    # setting the experiment start and end time stamps
                    time_format = '%d/%m/%Y %H.%M.%S'
                    exp_start_str = temp_booking.slot_date + ' ' + temp_booking.start_time + '.00'
                    exp_end_str = temp_booking.slot_date + ' ' + temp_booking.end_time + '.00'
                    exp_start_ts = datetime.datetime.fromtimestamp(time.mktime(time.strptime(exp_start_str, time_format)))
                    exp_end_ts = datetime.datetime.fromtimestamp(time.mktime(time.strptime(exp_end_str, time_format)))
                    exp_end_ts = exp_end_ts - datetime.timedelta(minutes=5) # adding a 5 minute buffer before experiment end time
                    # check if user is within the slot time
                    if cur_dt >= exp_start_ts and cur_dt <= exp_end_ts:
                        exp_end_timestamp = time.mktime(exp_end_ts.utctimetuple())
                        exp_diff_ts = time.mktime(exp_end_ts.utctimetuple()) - time.mktime(cur_dt.utctimetuple())
                        exp_diff_ts = int(exp_diff_ts / 60)
                        cur_booking = temp_booking
                        break
                except:
                    continue
        else:
            html = json.dumps(['S', '0', 'No valid slot found'])
            return HttpResponse(html)
        if not cur_booking:
            html = json.dumps(['S', '0', 'No valid slot found for today. Please note that you cannot start a experiment within last 5 minutes of end time'])
            return HttpResponse(html)

        # test connection to SBHS device by reading the temperature value
        testconn = sbhs.Sbhs()
        res = testconn.connect(cur_booking.mid)
        if not res:
            html = json.dumps(['S', '0', 'Failed to connect to the SBHS device'])
            return HttpResponse(html)
        testtemp = testconn.getTemp()
        testconn.disconnect()
        if testtemp < 1.0:
            html = json.dumps(['S', '0', 'Failed to communicate with the SBHS device'])
            return HttpResponse(html)

        # set the log file name and create the necessary folders
        # log file name format : LOG_FILE_BASE_PATH / ROLLNO / TIMESTAMP.txt
        log_file_name = datetime.datetime.now().strftime('%d%b%Y_%H_%M_%S') + ".txt"
        # check if user folder exists
        log_file_folder = log_file_path + rollno + "/"
        if not os.path.exists(log_file_folder):
            try:
                os.makedirs(log_file_folder)
            except:
                clearsession(request)
                html = json.dumps(['S', '0', 'Failed to create user folder'])
                return HttpResponse(html)
        # check if file exists and try to write to it
        if os.path.isfile(log_file_folder + log_file_name):
            clearsession(request)
            html = json.dumps(['S', '0', 'Log file already exists'])
            return HttpResponse(html)
        try:
            lf = open(log_file_folder + log_file_name, "w")
            lf.close()
        except:
            clearsession(request)
            html = json.dumps(['S', '0', 'Failed to create log file'])
            return HttpResponse(html)

        # if user and slot validated and everything is ok then set the session data
        request.session['logged_in'] = '1'
        request.session['slot_id'] = cur_booking.slot_id
        request.session['rollno'] = cur_booking.rollno
        request.session['slot_date'] = cur_booking.slot_date
        request.session['end_time'] = int(exp_end_timestamp)
        request.session['mid'] = cur_booking.mid
        request.session['log_file'] = log_file_folder + log_file_name
        html = json.dumps(['S', '1', 'Login Successful and slot found. You have ' + str(exp_diff_ts) + ' minutes remaining', log_file_name])
        return HttpResponse(html)
    else:
        clearsession(request)
        return HttpResponse("Please use the SBHS Client")

@csrf_exempt
def endexp(request):
    """ end experimentand reset board  """
    s = sbhs.Sbhs()
    if request.session.get('mid', None): 
        res = s.connect(request.session.get('mid', None))
        if res:
            s.reset_board()
            s.disconnect()

    # delete user session data
    clearsession(request)
    html = json.dumps(['S', '1', 'Experiment over. Thank you for using the SBHS Project'])
    return HttpResponse(html)

@csrf_exempt
def communicate(request):
    """ read and write data from sbhs """
    if request.method != "POST":
        html = json.dumps(['S', '0', 'Please use the SBHS Client'])
        return HttpResponse(html)

    # check if user is logged in
    if not request.session.get('logged_in', None):
        clearsession(request)
        html = json.dumps(['S', '0', 'Please login before reading data from SBHS'])
        return HttpResponse(html)

    # server packet received timestamp in UNIX EPOCH millisecond 
    server_start_ts = int(time.time() * 1000)

    # check if experiment end time has reached
    exp_end_timestamp = request.session.get('end_time', None)
    if not exp_end_timestamp:
        html = json.dumps(['S', '0', 'Cannot retrive the experiment end time'])
        return HttpResponse(html)
    if exp_end_timestamp < time.time():
        html = json.dumps(['S', '1', 'END'])
        return HttpResponse(html)

    # connect to SBHS
    s = sbhs.Sbhs()
    res = s.connect(request.session.get('mid', None))
    if not res:
        html = json.dumps(['S', '0', 'Cannot connect to SBHS'])
        return HttpResponse(html)

    # get scilab client iteration
    scilab_client_iteration = request.POST.get('iteration', None)
    if not scilab_client_iteration:
        s.disconnect()
        html = json.dumps(['S', '0', 'Invalid scilab client iteration number'])
        return HttpResponse(html)

    # get scilab client timestamp
    scilab_client_timestamp = request.POST.get('timestamp', None)
    if not scilab_client_timestamp:
        s.disconnect()
        html = json.dumps(['S', '0', 'Invalid scilab client timestamp'])
        return HttpResponse(html)

    # get scilab client variable arguments
    scilab_client_variables = request.POST.get('variables', None)
    if not scilab_client_variables:
        scilab_client_variables = ''

    # set heat value
    err = False
    scilab_client_heat = request.POST.get('heat', None)
    if scilab_client_heat:
        try:
            heat = int(scilab_client_heat)
        except:
            err = True
            errMsg = 'Invalid heat value'
        # write heat value to SBHS
        if not s.setHeat(heat):
            err = True
            errMsg = 'Error writing heat value to SBHS'
    else:
        err = True
        errMsg = 'Please specify heat value'
    # check for error message when setting heat
    if err:
        s.disconnect()
        html = json.dumps(['S', '0', errMsg])
        return HttpResponse(html)

    # set fan value
    err = False
    scilab_client_fan = request.POST.get('fan', None)
    if scilab_client_fan:
        try:
            fan = int(scilab_client_fan)
        except:
            err = True
            errMsg = 'Invalid fan value'
        # write fan value to SBHS
        if not s.setFan(fan):
            err = True
            errMsg = 'Error writing fan value to SBHS'
    else:
        s.disconnect()
        err = True
        errMsg = 'Please specify fan value'
    # check for error message when setting fan
    if err:
        s.disconnect()
        html = json.dumps(['S', '0', errMsg])
        return HttpResponse(html)

    # read current temperature
    temperature = s.getTemp()
    if temperature < 1.0:
        s.disconnect()
        html = json.dumps(['S', '0', 'Invalid temperature value'])
        return HttpResponse(html)

    # all SBHS read and write completed
    s.disconnect()

    # server processing end timestamp
    server_end_ts = int(time.time() * 1000)

    # return data to user
    server_data = "%s %s %s %2.2f" % (scilab_client_iteration, scilab_client_heat, scilab_client_fan, temperature)
    server_data = "%s %s %d %d" % (server_data, scilab_client_timestamp, server_start_ts, server_end_ts)

    # write to log file
    log_file = request.session.get('log_file', None)
    if not log_file:
        clearsession()
        html = json.dumps(['S', '0', 'Log file not found'])
        return HttpResponse(html)
    try:
        lf = open(log_file, "a")
        if scilab_client_variables:
            lf.write(server_data + ' ' + scilab_client_variables + '\n')
        else:
            lf.write(server_data + '\n')
        lf.close()
    except:
        clearsession()
        html = json.dumps(['S', '0', "Error writing to server log file"])
        return HttpResponse(html)

    html = json.dumps(['D', '1', server_data, scilab_client_variables])
    return HttpResponse(html)

def clearsession(request):
    """ clear the user session data """
    if request.session.get('logged_in', None):
        del request.session['logged_in']
    if request.session.get('slot_id', None):
        del request.session['slot_id']
    if request.session.get('rollno', None):
        del request.session['rollno']
    if request.session.get('slot_date', None):
        del request.session['slot_date']
    if request.session.get('start_time', None):
        del request.session['start_time']
    if request.session.get('end_time', None):
        del request.session['end_time']
    if request.session.get('mid', None):
        del request.session['mid']
    if request.session.get('log_file', None):
        del request.session['log_file']
