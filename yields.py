import json
import abis
import requests
from web3 import Web3

BASE = 1.0001
START_STATS_TIMESTAMP = 1691849719
INITIAL_MST_SUPPLY = 7000000*10**18
SECONDS_PER_YEAR = 31536000
SECONDS_PER_DAY = 60 * 60 * 24
DAYS_PER_YEAR = 365
LEND_ORACLE_PRECISION = 100000000
MIN_BLOCK_DIFF = 100
BLOCK_INCREMENT = 5000
CONVERSION_FACTOR =  10 ** 18
RAY = 10**27


def get_provider(rpc_list):
    """Iterate through the RPC list to find a working provider."""
    for rpc in rpc_list:
        try:
            provider = Web3(Web3.HTTPProvider(rpc))
            # Test the connection
            provider.eth.blockNumber
            return provider
        except requests.exceptions.RequestException as e:
            print(f"RPC Error: {e} - RPC: {rpc}")
        except Exception as e:
            print(f"Unexpected error: {e} - RPC: {rpc}")
            continue
    raise RuntimeError("All RPC endpoints failed.")


def update_liquidity_rate(w3, network, asset_symbol):
    dataProviderAddress = config[network]["contracts"]["MeridianProtocolDataProvider"]
    dataProviderABI = abis.MeridianProtocolDataProvider()
    dataProviderContract = w3.eth.contract(address=dataProviderAddress, abi=dataProviderABI)
    assetData = dataProviderContract.functions.getReserveData(config[network]["lending_tokens"][asset_symbol]["token"]).call()
    return assetData[3] 

def update_borrow_rate(w3, network, asset_symbol):
    dataProviderAddress = config[network]["contracts"]["MeridianProtocolDataProvider"]
    dataProviderABI = abis.MeridianProtocolDataProvider()
    dataProviderContract = w3.eth.contract(address=dataProviderAddress, abi=dataProviderABI)
    token = config[network]["lending_tokens"][asset_symbol]["token"]
    assetData = dataProviderContract.functions.getReserveData(token).call()
    return assetData[4] 


def get_rewards_per_second(w3, network, address):
    token_contract = w3.eth.contract(address=config[network]["contracts"]["pullRewardsIncentivesController"], abi=abis.pullRewardsIncentivesController())
    rewards_per_second = token_contract.functions.getAssetData(address).call()
    return rewards_per_second[1] * 10 ** -8


def fetch_token_prices(network, w3, asset):
    lend_oracle =  w3.eth.contract(address=config[network]["contracts"]["lend_oracle"], abi=abis.lend_oracle())
    return lend_oracle.functions.getAssetPrice(asset).call() * 10 ** -8


def get_token_supply(w3, token):
    oTokenContract = w3.eth.contract(address=token, abi=abis.token())
    return oTokenContract.functions.totalSupply().call()


def update_lending_yields():
    with open("json/lending/yields.json", "w") as jsonFile:
        json.dump(lend_yields, jsonFile)
   
with open("json/config.json", "r") as jsonFile:
    config = json.load(jsonFile)

with open("json/lending/yields.json", 'r') as file:
    lend_yields = json.load(file)
         
def update_interest_rates():
  for network in config:
    if not config[network].get("lend_active", False):
        continue
        
    w3 = get_provider(config[network]["rpcs"])
    
    if network not in lend_yields:
        lend_yields[network] = {}

    for asset_symbol in config[network]["lending_tokens"]:
        if asset_symbol not in lend_yields[network]:
            lend_yields[network][asset_symbol] = {"apr_base": 0,
                                                  "apr_base_borrow": 0, 
                                                  "apr_reward": 0, 
                                                  "apr_reward_borrow": 0,
                                                  "total_deposit_yield": 0,
                                                  "total_borrow_yield": 0}

        # Update rates using lending and borrowing base rates
        variable_borrow_rate = update_borrow_rate(w3, network, asset_symbol)
        liquidity_rate = update_liquidity_rate(w3, network, asset_symbol)
        
        deposit_apr = 100 * (liquidity_rate / RAY)
        borrow_apr = 100 * (variable_borrow_rate / RAY)
        
        # Store APR as a percentage
        lend_yields[network][asset_symbol]["apr_base"] = deposit_apr
        lend_yields[network][asset_symbol]["apr_base_borrow"] = borrow_apr 
        
        # Reward calculation requires correct decimal adjustment
        reward_token = config[network]["contracts"]["lending_reward_token"]
        reward_token_price = fetch_token_prices(network, w3, reward_token)
        token = config[network]["lending_tokens"][asset_symbol]["token"]
        token_price = fetch_token_prices(network, w3, token)
        token_decimals = config[network]["lending_tokens"][asset_symbol]["decimals"]

        o_token_address = config[network]["lending_tokens"][asset_symbol]["oToken"]
        debt_token_address = config[network]["lending_tokens"][asset_symbol]["debtToken"]
        
        o_token_supply = get_token_supply(w3, o_token_address)
        debt_token_supply = get_token_supply(w3, debt_token_address)

        o_token_emission_per_second = get_rewards_per_second(w3, network, config[network]["lending_tokens"][asset_symbol]["oToken"])
        debt_token_emission_per_second = get_rewards_per_second(w3, network, config[network]["lending_tokens"][asset_symbol]["debtToken"])
        
        if network == "taiko":
            print(o_token_emission_per_second, "o_token_emission_per_second")
        # Applying decimal adjustment to token supply and emission rates
        adjusted_o_token_supply = o_token_supply / (10 ** token_decimals)
        adjusted_debt_token_supply = debt_token_supply / (10 ** token_decimals)
        
        if o_token_emission_per_second>0:
            reward_deposit_apr = (o_token_emission_per_second * SECONDS_PER_YEAR * reward_token_price) / (adjusted_o_token_supply * token_price * LEND_ORACLE_PRECISION)
        else:
            reward_deposit_apr = 0
        
        if debt_token_emission_per_second>0:
            reward_borrow_apr = (debt_token_emission_per_second * SECONDS_PER_YEAR * reward_token_price) / (adjusted_debt_token_supply * token_price * LEND_ORACLE_PRECISION)
        else:
            reward_borrow_apr = 0
            
        if network == "meter":
            reward_deposit_apr = 0
            reward_borrow_apr = 0
            
        lend_yields[network][asset_symbol]["apr_reward"] = reward_deposit_apr
        lend_yields[network][asset_symbol]["apr_reward_borrow"] = reward_borrow_apr
        
        lend_yields[network][asset_symbol]["total_deposit_yield"] = reward_deposit_apr + deposit_apr
        lend_yields[network][asset_symbol]["total_borrow_yield"] = reward_borrow_apr - borrow_apr
        
        update_lending_yields()
        