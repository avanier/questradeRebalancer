#!/bin/env python2

import argparse
from sys import float_info
from sys import argv
from questrade.api import account
from questrade.api import api_utils
from questrade.api import market
from questrade.api.enumerations import OrderStateFilterType

QUESTRADE_ECN = 0.0035
DOLLAR_COST_AVERAGE = 1.0

def getSymbolTargetRatiosForAccount(accountType):
    return { 'Margin' : { 'VCN.TO': 30, 'XUU.TO': 30, 'XEF.TO': 23, 'XEC.TO': 7, 'ZDB.TO': 10 },
             'TFSA'   : { 'VCN.TO': 30, 'XUU.TO': 30, 'XEF.TO': 23, 'XEC.TO': 7, 'ZAG.TO': 10 },
             'RRSP'   : { 'VCN.TO': 30, 'XUU.TO': 30, 'XEF.TO': 23, 'XEC.TO': 7, 'ZAG.TO': 10 } 
           }[accountType]

def getAvailableCash(accountId):
    balances = account.accounts_balances(accountId)
    cashBalances = balances['perCurrencyBalances']
    for currency in cashBalances:
        if (currency['currency'] == 'CAD'):
            return currency['cash']
    return None

def getPositionsValues(accountId, symbols):
    positionValues = {}
    for symbol in symbols:
        positionValues[symbol] = 0

    positionsTotal = 0
    positions = account.accounts_positions(accountId)
    for position in positions['positions']:
        symbol = position['symbol']
        if symbol in positionValues:
            value = position['currentMarketValue']
            positionValues[symbol] = value
            positionsTotal += value

    return (positionsTotal, positionValues)

def getInternalSymbols(symbols):
    symbolIdDict = {}
    for symbol in symbols:
        symbolId = int(api_utils.lookup_symbol_id(symbol))
        symbolIdDict[symbol] = symbolId

    return symbolIdDict

def getSymbolQuotes(symbolIds):
    symbolQuotes = {}
    quotes = market.markets_quotes(symbolIds)
    for quote in quotes['quotes']:
        symbolQuotes[quote['symbol']] = quote['askPrice']
    
    return symbolQuotes

def getSymbolOfSmallestTargetRatioDifferences(positionsTotal, symbolTargetRatios, symbolQuotes, positionValues):
    minMagDiff = float_info.max
    minSymbol = None

    for selectedSymbol in symbolTargetRatios.keys():
        total = positionsTotal + symbolQuotes[selectedSymbol]

        sumOfMagDiff = 0
        for symbol, positionValue in positionValues.iteritems():
            value = positionValue
            if selectedSymbol == symbol:
                value += symbolQuotes[selectedSymbol]
            diff = (symbolTargetRatios[symbol] / 100.0) - (value / total)
            sumOfMagDiff += diff * diff

        if sumOfMagDiff < minMagDiff:
            minMagDiff = sumOfMagDiff
            minSymbol = selectedSymbol

    return minSymbol

def getBuyOrders(cashTotal, positionsTotal, symbolTargetRatios, symbolQuotes, positionValues):
    buyOrders = {}
    remaining = cashTotal
    newPositionsTotal = positionsTotal
 
    while remaining > QUESTRADE_ECN:
        # Buy the stock which will produce the smallest difference in ratios
        symbol = getSymbolOfSmallestTargetRatioDifferences(
            newPositionsTotal, symbolTargetRatios, symbolQuotes, positionValues)
        
        # If we can't afford the optimum stock then stop
        if not symbol or (symbolQuotes[symbol] + QUESTRADE_ECN) > remaining:
            break

        buyOrders[symbol] = buyOrders.get(symbol, 0) + 1
        remaining -= symbolQuotes[symbol] + QUESTRADE_ECN
        newPositionsTotal += symbolQuotes[symbol]
        positionValues[symbol] += symbolQuotes[symbol]

    return buyOrders

def placeBuyOrders(accountId, symbolIdDict, buyOrders, symbolQuotes):
    openOrders = account.accounts_orders(accountId, state_filter=OrderStateFilterType.Open)
    for openOrder in openOrders['orders']:
        if openOrder['symbol'] in buyOrders:
            print "There is an open order for {0} on account {1}, stopping.".format(openOrder['symbol'], accountId)
            return False

    for symbol, toBuy in buyOrders.iteritems():
        order = account.accounts_place_order(accountId, symbolIdDict[symbol], toBuy, symbolQuotes[symbol])['orders'][0]
        if order['rejectionReason'] != '':
            print "Order for {0} x {1} @ {2} on account {3} was rejected for reason '{4}', stopping.".format(
                toBuy, symbol, symbolQuotes[symbol], accountId, order['rejectionReason'])
            return False
        print "Order for {0} x {1} @ {2} on account {3} was placed successfully.".format(toBuy, symbol, symbolQuotes[symbol], accountId)
    
    return True

def rebalance(accountId, symbolTargetRatios, buyMode):
    symbols = symbolTargetRatios.keys()

    cashTotal = getAvailableCash(accountId) / DOLLAR_COST_AVERAGE

    symbolIdDict = getInternalSymbols(symbols)
    positionsTotal, positionValues = getPositionsValues(accountId, symbols)

    symbolQuotes = getSymbolQuotes(symbolIdDict.values())
    for symbol, quote in symbolQuotes.iteritems():
        if not quote:
            print "Something went wrong getting the quote of {0}, stopping.".format(symbol)
            return False 

    buyOrders = getBuyOrders(cashTotal, positionsTotal, symbolTargetRatios, symbolQuotes, positionValues)
    if (buyMode):
        return placeBuyOrders(accountId, symbolIdDict, buyOrders, symbolQuotes)
    else:
        for symbol, toBuy in buyOrders.iteritems():
            print "Would place order for {0} x {1} @ {2} on account {3}".format(
                toBuy, symbol, symbolQuotes[symbol], accountId)
        return True

parser = argparse.ArgumentParser(description='Buy some ETFs')
subparsers = parser.add_subparsers(dest='command')
listAccounts = subparsers.add_parser('listAccounts', help='Lists your Questrade accounts')
showOrders = subparsers.add_parser('showOrders', help='Shows the orders that would be made')
showOrders.add_argument('accountType', help='The type of the account')
showOrders.add_argument('accountNumber', help='The number of the account')
placeOrders = subparsers.add_parser('spendAllMyMoney', help='WARNING will spend all your money!!! Places orders to rebalance your account')
placeOrders.add_argument('accountType', help='The type of the account')
placeOrders.add_argument('accountNumber', help='The number of the account')
args = parser.parse_args()

if args.command == 'listAccounts':
    accounts = account.accounts()
    for acc in accounts['accounts']:
        print acc['type'], acc['number']
        exit(0)
else:
    buyMode = args.command == 'spendAllMyMoney'

    accountType = args.accountType
    accountNumber = args.accountNumber
    if rebalance(accountNumber, getSymbolTargetRatiosForAccount(accountType), buyMode):
        if buyMode:
            print "All orders on account {0} were placed successfully.".format(accountNumber)
        exit(0)
    else:
        print "There was a problem placing orders on account {0}, stopping.".format(accountNumber)
        exit(1)