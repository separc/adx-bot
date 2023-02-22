#
# Notes:
# Future improvements possible:
# 1 - Print graph for each Top5, including moving (EMA) avg and ADX
# 2 - Possibility to select number from 1 to 5 and automatically create 3Commas bots + run

import ccxt
import time
import math
import config
import sys
from time import gmtime, strftime
from py3cw.request import Py3CW
from pathlib import Path
from datetime import timezone
import datetime
import numpy as np
import pandas as pd
import pandas_ta as ta
import operator
from plotly_functions import *


# Setup
p3cw = Py3CW(
    key=config.TC_API_KEY,
    secret=config.TC_API_SECRET,
    request_options={
        'request_timeout': 30,
        'nr_of_retries': 5,
        'retry_status_codes': [500, 502, 503, 504]
    }
)

#binance = ccxt.binance({
#    'apiKey': config.API_KEY,
#    'secret': config.SECRET_KEY
#})
binance = ccxt.binanceusdm()

def get_markets():
    trycnt = 4
    while trycnt > 0:
        try:
            all_markets = binance.load_markets(True)
            trycnt = 0
        except Exception as e:
            print("Connection error, trying again...")
            f = open("3ctrigger_log.txt", "a")
            f.write(f'Exchange connection error at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
            f.close()
            trycnt -= 1
            if trycnt == 3:
                time.sleep(3)
            elif trycnt == 2:
                time.sleep(15)
            elif trycnt == 1:
                time.sleep(45)
        else:
            return all_markets

def build_tc_pairs_list(pairs):
    tc_pairs = {}
    for key in markets:
        if ("PERP" in markets[key]["info"]["contractType"] 
            and not any(perp in markets[key]["symbol"] for perp in config.PAIRS_BLACKLIST)):
            tc_pairs[markets[key]["id"]] = ""
    return tc_pairs


def get_tradeable_balance():
    trycnt = 4
    while trycnt > 0:
        try:
            account_balances = binance.fetch_balance()
            balance = account_balances["total"]["USD"]
            print(f'Balance: {balance}')
            trycnt = 0
        except Exception as e:
            print("Connection error, trying again...")
            f = open("3ctrigger_log.txt", "a")
            f.write(f'Exchange connection error at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
            f.close()
            trycnt -= 1
            if trycnt == 3:
                time.sleep(3)
            elif trycnt == 2:
                time.sleep(15)
            elif trycnt == 1:
                time.sleep(45)
        else:
            return balance


def start_bot(pair, ids):
    bot_id = ids[pair]
    f = open("3ctrigger_log.txt", "a")
    f.write(f'Enable bot for {pair} at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
    f.close()
    error, bot_trigger = p3cw.request(
        entity = 'bots',
        action = 'enable',
        action_id = bot_id
    )   
    print(f'Bot Enabled for {pair} - {bot_id}')
    return bot_trigger


def close_deal(pair, bot_id):
    if type(bot_id) is not int:
        bot_id = bot_id[pair]
    f = open("3ctrigger_log.txt", "a")
    f.write(f'Panic Close - {pair}  - {bot_id} at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
    f.close()
    error, deal_close = p3cw.request(
        entity = 'bots',
        action = 'panic_sell_all_deals',
        action_id = str(bot_id)
    )
    print(f'Panic Close - {pair}')
    time.sleep(5)
    return deal_close


def get_positions():
    open_positions = {}
    all_positions = binance.fetchPositions(None, {"showAvgPrice": True})
    if 'info' in all_positions[0]:
        for y in all_positions:
            x=y['info']
            future = (x["future"])
            size = (x["size"])
            side = (x["side"])
            cost = (x["cost"])
            recentAverageOpenPrice = (x["recentAverageOpenPrice"])
            if size != '0.0':
                open_positions[future] = size, side, cost, recentAverageOpenPrice
    else:
        for x in all_positions:
            future = (x["future"])
            size = (x["size"])
            side = (x["side"])
            cost = (x["cost"])
            recentAverageOpenPrice = (x["recentAverageOpenPrice"])
            if size != '0.0':
                open_positions[future] = size, side, cost, recentAverageOpenPrice
        
    return open_positions

def load_bot_ids(filename):
    d = {}
    with open(filename) as f:
        for line in f:
            (key, val) = line.split(':')
            d[key] = val.rstrip('\n')
    return d


def get_max_bot_usage(balance):
    if config.MARTINGALE_VOLUME_COEFFICIENT == 1.0:
        max_bot_usage = (config.BASE_ORDER_VOLUME + (config.SAFETY_ORDER_VOLUME*config.MAX_SAFETY_ORERS)) / config.LEVERAGE_CUSTOM_VALUE
    else:
        max_bot_usage = (config.BASE_ORDER_VOLUME + (config.SAFETY_ORDER_VOLUME*(config.MARTINGALE_VOLUME_COEFFICIENT**config.MAX_SAFETY_ORERS - 1) / (config.MARTINGALE_VOLUME_COEFFICIENT - 1))) / config.LEVERAGE_CUSTOM_VALUE
    return max_bot_usage


def disable_bot(pair, bot_id):
    f = open("3ctrigger_log.txt", "a")
    f.write(f'Disable bot for {pair} - {bot_id} at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
    f.close()
    error, data = p3cw.request(
        entity='bots',
        action='disable',
        action_id = str(bot_id),
    )
    print(f'Error: {error}')
    print(f'Bot Disabled for {pair} - {bot_id}')
    

def get_bot_info():
    data = []
    bot_info = []
    first_run = True
    base_offset = 100
    offset = 0
    while len(data) == 100 or first_run:
        first_run = False
        error, data = p3cw.request(
            entity='bots',
            action='',
            payload={
                "account_id": config.TC_ACCOUNT_ID,
                "limit": base_offset,
                "offset": offset,
            }
        )
        if type(data) is not list:
            print("Data from 3Commas is not a list.")
            print(data)
            data = []
        bot_info = bot_info + data
        offset += base_offset
    return bot_info

def get_enabled_bots():
    enabled_bots = {}
    bot_list = get_bot_info()
    for bot in bot_list:
        if bot["is_enabled"] == True:
            bot_id = bot["id"]
            bot_pair = bot["pairs"][0]
            bot_strategy = bot["strategy"]
            enabled_bots[bot_pair[4:]] = bot_id, bot_strategy
    return enabled_bots


def perp_stats(perp):
    stats = []
    time_frame_mins = config.TF
    htf_mins = time_frame_mins * config.HTF_MULTIPLIER
    adx_length = config.ADX_LENGTH
    ema_length = config.EMA_LENGTH
    htf_fast_ema = config.HTF_FAST_EMA
    htf_slow_ema = config.HTF_SLOW_EMA
    look_back = max(adx_length, ema_length)*4
    htf_look_back = htf_slow_ema * 4
    current_time = datetime.datetime.now()
    from_time = current_time - datetime.timedelta(minutes = time_frame_mins*look_back)
    htf_from_time = current_time - datetime.timedelta(minutes = htf_mins*htf_look_back)
    from_time_stamp = int(from_time.timestamp() * 1000)
    htf_from_time_stamp = int(htf_from_time.timestamp() * 1000)
    if time_frame_mins < 60:
        time_frame = time_frame_mins
        time_frame_units = 'm'
    elif time_frame_mins >= 60:
        time_frame = int(time_frame_mins//60)
        time_frame_units = 'h'

    if htf_mins < 60:
        htf_time_frame = htf_mins
        htf_units = 'm'
    elif htf_mins >= 60:
        htf_time_frame = int(htf_mins//60)
        htf_units = 'h'
    
    trycnt = 4
    while trycnt > 0:
        try:
            candles = binance.fetch_ohlcv(perp, str(int(time_frame)) + time_frame_units, from_time_stamp)
            time.sleep(1)
            if config.HTF_VALIDATE:
                htf_candles = binance.fetch_ohlcv(perp, str(int(htf_time_frame)) + htf_units, htf_from_time_stamp)
            trycnt = 0
        except Exception as e:
            print("Connection error, trying again...")
            f = open("3ctrigger_log.txt", "a")
            f.write(f'Exchange connection error at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
            f.close()
            trycnt -= 1
            if trycnt == 3:
                time.sleep(3)
            elif trycnt == 2:
                time.sleep(15)
            elif trycnt == 1:
                time.sleep(45)
        else:
            # Load data into a pandas dataframe
            df = pd.DataFrame(np.array(candles), columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
            # Get ADX and DMI values
            df.ta.adx(close='Close', length=adx_length, append=True)
            # Get ADX Slope
            df['ADX_SLOPE'] = df['ADX_'+str(adx_length)].diff()
            # Get EMA Values 
            df.ta.ema(close='Close', length=ema_length, append=True)
            # Calculate normalized Slope of EMA values
            df['EMA_SLOPE'] = df['EMA_'+str(ema_length)].diff().abs() / df['EMA_'+str(ema_length)]
            # Calculate EMA(3) of slope values
            df['EMA_SMOOTH'] = df['EMA_SLOPE'].ewm(span=config.EMA_SMOOTHING).mean()
            # SPARENT : Add EMA or MA 1 to get the last price??

            # HTF Calcs
            if config.HTF_VALIDATE:
                df2 = pd.DataFrame(np.array(htf_candles), columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
                df2.ta.ema(close='Close', length=htf_fast_ema, append=True)
                df2.ta.ema(close='Close', length=htf_slow_ema, append=True)
                #ema_fast = df2.loc[(df.shape[0]-2), 'EMA_'+str(htf_fast_ema)]
                #ema_slow = df2.loc[(df.shape[0]-2), 'EMA_'+str(htf_slow_ema)]
                ema_fast = df2.loc[(df2.shape[0]-2), 'EMA_'+str(htf_fast_ema)]
                ema_slow = df2.loc[(df2.shape[0]-2), 'EMA_'+str(htf_slow_ema)]
                if ema_fast > ema_slow:
                    trend_dir = "up"
                elif ema_fast <= ema_slow:
                    trend_dir = "down"
            else:
                trend_dir = "null"


            if config.EARLY_CLOSE and df.loc[(df.shape[0]-2), 'ADX_SLOPE'] < df.loc[(df.shape[0]-3), 'ADX_SLOPE'] and df.loc[(df.shape[0]-3), 'ADX_SLOPE'] < df.loc[(df.shape[0]-4), 'ADX_SLOPE'] and df.loc[(df.shape[0]-4), 'ADX_SLOPE'] and df.loc[(df.shape[0]-5), 'ADX_SLOPE']:
                adx_direction = -1
            else:
                adx_direction = df.loc[(df.shape[0]-2), 'ADX_SLOPE']
            
            # Add values to a list
            stats.append(perp)
            stats.append(df.loc[(df.shape[0]-2), 'ADX_'+str(adx_length)])
            stats.append(adx_direction)
            stats.append(df.loc[(df.shape[0]-2), 'DMP_'+str(adx_length)])
            stats.append(df.loc[(df.shape[0]-2), 'DMN_'+str(adx_length)])
            stats.append(df.loc[(df.shape[0]-2), 'EMA_SMOOTH'])
            return stats, trend_dir


##    <<<<<<<<<<<   START OF PROGRAM HERE     >>>>>>>>>>>>>>>>>

open_positions = {}
unsorted_tradable_perps = []
sorted_tradable_perps = []
tradable_perps = {}
enabled_bots = {}

global markets
markets = get_markets()
pairs_list = build_tc_pairs_list(markets)


#tradeable_balance = get_tradeable_balance()
#
#bot_usage = get_max_bot_usage(tradeable_balance)
#
#print(f'Max bot usage: {bot_usage}')

# Calc max number of bots - constrained by bot usage

#if math.floor((float(tradeable_balance) * config.FUNDS_USAGE) / bot_usage) < config.MAX_OPEN_POSITIONS:
#    max_positions = math.floor((float(tradeable_balance) * config.FUNDS_USAGE) / bot_usage)
#else:
#    max_positions = config.MAX_OPEN_POSITIONS
#
#print(f'Max positions: {max_positions}')
#
#last_balance_check = strftime("%Y-%m-%d", gmtime())

f = open("adx_explore_currentState_log.txt", "a")
f.write("<<<<>>>>\n")
f.write(f'Script Run at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
f.write(f'Time-frame: {config.TF}\n')
#f.write(f'Balance: {tradeable_balance}, Max Positions: {max_positions}\n')
f.write("<<<<>>>>\n")
f.close()

update_stats_time = True

##    <<<<<<<<<<<   START LOOP HERE     >>>>>>>>>>>>>>>>>

while True:
    time.sleep(0.5) # Give the CPU a break.
    while update_stats_time:
        print('Getting perps OHLCV data...')
        # for perp in long_bot_ids:
        for perp in pairs_list:
            print(".", end =" ")
            unfiltered_stats, trend_direction = perp_stats(perp)
            ADX = unfiltered_stats[1]
            ADX_Slope = unfiltered_stats[2]
            DM_plus = unfiltered_stats[3]
            DM_minus = unfiltered_stats[4]
            if ADX > config.ADX_MINVAL and (ADX_Slope > 0 and ((DM_plus > DM_minus and ADX > DM_minus) or (ADX < DM_plus and ADX < DM_minus))) and DM_plus > DM_minus and trend_direction == "up":
                unfiltered_stats.append("long")
                unsorted_tradable_perps.append(unfiltered_stats)
            elif ADX > config.ADX_MINVAL and (ADX_Slope > 0 and ((DM_plus < DM_minus and ADX > DM_plus) or (ADX < DM_plus and ADX < DM_minus))) and DM_plus < DM_minus and trend_direction == "down":
                unfiltered_stats.append("short")
                unsorted_tradable_perps.append(unfiltered_stats)
            elif ADX_Slope < 0:
                unfiltered_stats.append("disable")
                unsorted_tradable_perps.append(unfiltered_stats)
            else:
                unfiltered_stats.append("ignore")
                unsorted_tradable_perps.append(unfiltered_stats)

        print(".")    
        # Sort the lists by EMA Slope

        sorted_tradable_perps = sorted(unsorted_tradable_perps, key=operator.itemgetter(5), reverse = True)

        # Convert list to dictionary
        number_of_perps = len(sorted_tradable_perps)
        i = 0
        for i in range(number_of_perps):
            tradable_perps[sorted_tradable_perps[i][0]] = sorted_tradable_perps[i][1], sorted_tradable_perps[i][2], sorted_tradable_perps[i][3], sorted_tradable_perps[i][4], sorted_tradable_perps[i][5], sorted_tradable_perps[i][6]
        
        # SPARENT: Print TOP 5 to terminal
        print("Current Top 5 Perps with ADX:")
        timeframe = str(config.TF) + 'm'
        ii = 0
        for ii in range(5):
            print(f'{ii + 1} - {list(tradable_perps)[ii]} : {sorted_tradable_perps[ii][1]}')
            plot_ohlcv_with_indicators(list(tradable_perps)[ii], timeframe)

        #open_positions = get_positions()
        #print("Open Positions:")
        #print(open_positions)
        #
        #enabled_bots = get_enabled_bots()
        #print("Enabled Bots:")
        #print(enabled_bots)
        #
        #available_bots = max_positions - max(len(enabled_bots), len(open_positions))
       
        ## Disable a bot if ADX slope goes negative.
        #for adx_perp in enabled_bots:
        #    if adx_perp in tradable_perps:
        #        if tradable_perps[adx_perp][5] == "disable" or tradable_perps[adx_perp][5] == "ignore":
        #            disable_bot(adx_perp, enabled_bots[adx_perp][0])
        #            if config.CLOSE_DEALS_WITH_BOT:
        #                close_deal(adx_perp, enabled_bots[adx_perp][0])
        #
        #time.sleep(10) # Small delay, closing positions above lag execution of following two lines.
        #
        #open_positions = get_positions()
        #
        #enabled_bots = get_enabled_bots()
        #
        #available_bots = max_positions - max(len(enabled_bots), len(open_positions))
        #
        #
        #print(f'Open positions: {len(open_positions)}')
        #print(f'Enabled Bots: {len(enabled_bots)}')
        #print(f'Available Bots: {available_bots}')
        #print(f'Max Positions: {max_positions}')
        #
        #if tradable_perps and available_bots > 0:
        #    print("Getting ready to enable bots....")
        #    for trade_perp in tradable_perps:
        #        if trade_perp not in enabled_bots and available_bots > 0:
        #            if tradable_perps[trade_perp][5] == "long":
        #                trigger_long = start_bot(trade_perp, long_bot_ids)
        #                available_bots -= 1
        #                print("<<<>>>")
        #            elif tradable_perps[trade_perp][5] == "short":
        #                trigger_short = start_bot(trade_perp, short_bot_ids)
        #                available_bots -= 1
        #                print("<<<>>>")

        update_stats_time = False
        # SPARENT : Write to file TOP 5 ?
        # write to file next expected checkin time.
        next_update = datetime.datetime.now() + datetime.timedelta(seconds=config.TF*60)
        f = open("adx_explore_currentState_log.txt", "a")
        f.write(f'Next update at {str(next_update)}\n')
        f.close()
        print("Waiting for next TF....")
        time.sleep(60)
        

    open_positions.clear()
    unsorted_tradable_perps.clear()
    sorted_tradable_perps.clear()
    tradable_perps.clear()
    enabled_bots.clear()


    #now = datetime.datetime.now()
    
    #if strftime("%Y-%m-%d", gmtime()) > last_balance_check:
    #    tradeable_balance = get_tradeable_balance()
    #    bot_usage = get_max_bot_usage(tradeable_balance)
    #    if math.floor((float(tradeable_balance) * config.FUNDS_USAGE) / bot_usage) < config.MAX_OPEN_POSITIONS:
    #        max_positions = math.floor((float(tradeable_balance) * config.FUNDS_USAGE) / bot_usage)
    #    else:
    #        max_positions = config.MAX_OPEN_POSITIONS
#
    #    last_balance_check = strftime("%Y-%m-%d", gmtime())
    #    f = open("3ctrigger_log.txt", "a")
    #    f.write(f'Updated Balance: {tradeable_balance}, Max Positions: {max_positions} at {strftime("%Y-%m-%d %H:%M:%S", gmtime())} UTC\n')
    #    f.write(">>>>\n")
    #    f.close()
    #    print(f'Updated Balance: {tradeable_balance}, Max Positions: {max_positions}')
        

    now = datetime.datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = ((now - midnight).seconds) // 60
    
    if (minutes % config.TF) == 0 :
        time.sleep(5)
        update_stats_time = True
