import websocket
import json
import threading
import time
import random
import logging
import sys
import asyncio
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("binary_options_bot.log"),
        logging.StreamHandler()
    ]
)

class DerivBinaryOptionsBot:
    def __init__(self, api_token, app_id):
        self.api_token = api_token
        self.app_id = app_id
        self.websocket_url = f"wss://ws.binaryws.com/websockets/v3?app_id={app_id}"
        self.ws = None
        self.ws_thread = None
        
        # Request ID counter
        self.req_id = 1
        
        # Bot state
        self.authorized = False
        self.active_markets = [
            "R_10", "R_25", "R_50", "R_75", "R_100",
            "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V"
        ]
        self.current_market = None
        self.active_contract = None
        
        # Trading parameters
        self.trade_duration = 1  # 1 minutes
        self.trade_duration_unit = "m"  # minutes
        self.sequence = []  # Sequence of trades (R/G)
        self.current_trade_index = 0
        
        # Predefined stakes for each round
        self.stakes = [
            0.35,      # Round 1
            0.60,     # Round 2
            1.61,     # Round 3
            4.34,    # Round 4
            11.69,    # Round 5
            31.49,   # Round 6
            84.82,   # Round 7
            228.47,  # Round 8
            615.40,  # Round 9
            1657.63  # Round 10
        ]
        self.max_consecutive_losses = len(self.stakes)
        self.consecutive_losses = 0
        
        # Trading state
        self.is_trading = False
        self.waiting_for_contract_settlement = False
    
    def get_next_req_id(self):
        """Get the next request ID and increment counter"""
        req_id = self.req_id
        self.req_id += 1
        return req_id
    
    def connect(self):
        """Establish WebSocket connection"""
        logging.info("Connecting to Deriv API...")
        self.ws = websocket.WebSocketApp(
            self.websocket_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        self.ws_thread = threading.Thread(target=self.ws.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread.start()
    
    def on_open(self, ws):
        """WebSocket connection opened"""
        logging.info("WebSocket connection opened")
        self.authorize()
    
    def on_message(self, ws, message):
        """Handle incoming messages"""
        data = json.loads(message)
        msg_type = data.get('msg_type')
        
        try:
            # Handle authorization
            if msg_type == 'authorize' and data.get('authorize'):
                self.authorized = True
                logging.info("Successfully authorized with Deriv API")
                # Start trading immediately instead of getting active symbols
                self.select_random_market()
                self.generate_sequence()
                self.start_trading_sequence()
            
            # Handle buy contract response
            elif msg_type == 'buy' and data.get('buy'):
                self.handle_buy_response(data)
            
            # Handle contract updates
            elif msg_type == 'proposal_open_contract' and data.get('proposal_open_contract'):
                self.handle_contract_update(data['proposal_open_contract'])
            
            # Handle errors
            elif data.get('error'):
                error_message = data['error']['message']
                error_code = data.get('error', {}).get('code', 'unknown')
                logging.error(f"API Error: {error_message} (Code: {error_code})")
                logging.error(f"Request that caused error: {json.dumps(data.get('echo_req', {}))}")
                
                # Check if error is insufficient balance
                if "balance" in error_message.lower() and "insufficient" in error_message.lower():
                    logging.critical("Insufficient balance. Exiting program.")
                    self.ws.close()
                    sys.exit(1)
                
                # If market is closed, try the next market
                if "market is closed" in error_message.lower() or "market" in error_message.lower():
                    logging.warning(f"Market {self.current_market} is closed. Trying next market.")
                    self.select_random_market()
                    self.start_trading_sequence()
        
        except Exception as e:
            logging.error(f"Error processing message: {str(e)}")
    
    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        logging.error(f"WebSocket Error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection closure"""
        logging.info(f"WebSocket connection closed: {close_status_code} - {close_msg}")
        # Attempt to reconnect after a brief pause
        time.sleep(5)
        self.connect()
    
    def authorize(self):
        """Authorize with the Deriv API"""
        req_id = self.get_next_req_id()
        self.ws.send(json.dumps({
            "authorize": self.api_token,
            "req_id": req_id
        }))
    
    def select_random_market(self):
        """Select a random market from active markets"""
        if not self.active_markets:
            logging.error("No active markets available")
            sys.exit(1)
        
        self.current_market = random.choice(self.active_markets)
        logging.info(f"Selected market: {self.current_market}")
    
    def generate_sequence(self):
        """Generate a random sequence of trades (R/G)"""
        self.sequence = random.choices(['R', 'G'], k=10)
        logging.info(f"Generated sequence: {''.join(self.sequence)}")
        self.current_trade_index = 0
    
    def get_current_stake(self):
        """Get the stake for the current loss streak"""
        if self.consecutive_losses >= len(self.stakes):
            logging.critical(f"Reached maximum consecutive losses ({self.max_consecutive_losses}). Exiting program.")
            self.ws.close()
            sys.exit(1)
        
        return self.stakes[self.consecutive_losses]
    
    def start_trading_sequence(self):
        """Start trading sequence"""
        if not self.authorized or not self.current_market:
            logging.error("Not authorized or no market selected")
            return
        
        self.is_trading = True
        self.waiting_for_contract_settlement = False
        self.consecutive_losses = 0
        self.place_next_trade()
    
    def place_next_trade(self):
        """Place the next trade in the sequence"""
        if not self.is_trading or self.waiting_for_contract_settlement:
            return
        
        if self.current_trade_index >= len(self.sequence):
            logging.warning("Reached end of sequence. Generating new sequence.")
            self.generate_sequence()
        
        # Get the next trade type
        trade_type = self.sequence[self.current_trade_index]
        contract_type = "PUT" if trade_type == 'R' else "CALL"
        
        self.place_trade(contract_type)
    
    def place_trade(self, contract_type):
        """Place a binary options trade"""
        if not self.authorized or not self.current_market:
            logging.error("Cannot place trade: Not authorized or no market selected")
            return
        
        current_stake = self.get_current_stake()
        
        # Log trade details
        logging.info(f"Placing {contract_type} trade on {self.current_market}")
        logging.info(f"Round: {self.consecutive_losses + 1}")
        logging.info(f"Stake: {current_stake}")
        logging.info(f"Trade index: {self.current_trade_index + 1} of {len(self.sequence)}")
        
        # Get a new request ID
        req_id = self.get_next_req_id()
        
        # Send trade request
        self.ws.send(json.dumps({
            "buy": 1,
            "price": current_stake,
            "parameters": {
                "amount": current_stake,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": self.trade_duration,
                "duration_unit": self.trade_duration_unit,
                "symbol": self.current_market
            },
            "req_id": req_id
        }))
        
        self.waiting_for_contract_settlement = True
    
    def handle_buy_response(self, data):
        """Handle the response after placing a contract"""
        buy_data = data.get('buy')
        req_id = data.get('req_id')
        
        if buy_data:
            contract_id = buy_data.get("contract_id")
            current_stake = self.get_current_stake()
            self.active_contract = {
                "contract_id": contract_id,
                "trade_index": self.current_trade_index,
                "trade_type": self.sequence[self.current_trade_index],
                "stake": current_stake,
                "req_id": req_id,
                "contract_type": "PUT" if self.sequence[self.current_trade_index] == 'R' else "CALL"
            }
            logging.info(f"Contract placed successfully. ID: {contract_id}")
            
            # Subscribe to contract updates
            subscription_req_id = self.get_next_req_id()
            self.ws.send(json.dumps({
                "proposal_open_contract": 1,
                "contract_id": contract_id,
                "subscribe": 1,
                "req_id": subscription_req_id
            }))
        else:
            logging.error(f"Failed to place contract. Request ID: {req_id}")
            # Move to the next market if there was an error
            self.select_random_market()
            self.start_trading_sequence()
    
    def handle_contract_update(self, contract_data):
        """Handle updates for an open contract"""
        if not self.active_contract:
            return
            
        contract_id = contract_data.get("contract_id")
        
        # Make sure this is our active contract
        if contract_id != self.active_contract["contract_id"]:
            return
            
        status = contract_data.get("status")
        
        if status == "open":
            # Contract still running
            return
            
        self.waiting_for_contract_settlement = False
        
        # Add contract type to contract data for the web interface
        contract_data["contract_type"] = self.active_contract.get("contract_type", "UNKNOWN")
        
        if status == "won":
            profit = contract_data.get("profit")
            logging.info(f"Contract won! Profit: {profit}")
            
            # Reset for new trading sequence
            self.consecutive_losses = 0
            self.select_random_market()
            self.generate_sequence()
            self.start_trading_sequence()
            
        elif status == "lost":
            loss = contract_data.get("profit")
            logging.info(f"Contract lost. Loss: {loss}")
            
            # Increment consecutive losses and trade index
            self.consecutive_losses += 1
            self.current_trade_index += 1
            
            # Check if we reached the end of the sequence
            if self.current_trade_index >= len(self.sequence):
                logging.info("Reached end of sequence. Generating new sequence.")
                self.generate_sequence()
            
            # Check if we've reached maximum losses
            if self.consecutive_losses >= len(self.stakes):
                logging.critical(f"Reached maximum consecutive losses ({self.max_consecutive_losses}). Exiting program.")
                self.ws.close()
                sys.exit(1)
            
            # Log information about the next stake
            next_stake = self.stakes[self.consecutive_losses]
            logging.info(f"Moving to round {self.consecutive_losses + 1} with stake: {next_stake}")
            
            # Place next trade immediately
            self.place_next_trade()
        
        # Clear active contract
        self.active_contract = None
    
    def run(self):
        """Main bot loop"""
        logging.info("Starting Deriv Binary Options Trading Bot")
        logging.info("Using synthetic indices markets:")
        for market in self.active_markets:
            logging.info(f"- {market}")
        
        logging.info("Using predefined stakes for each round:")
        for i, stake in enumerate(self.stakes):
            logging.info(f"Round {i+1}: ${stake:.2f}")
        
        self.connect()
        
        try:
            # Keep the main thread alive
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logging.info("Bot stopped by user")
            if self.ws:
                self.ws.close()
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            if self.ws:
                self.ws.close()

if __name__ == "__main__":
    # Replace with your actual API token and app_id
    API_TOKEN = "8fRRApGnNy0TY6T"  # Your API token
    APP_ID = "1089"  # Your app ID
    
    bot = DerivBinaryOptionsBot(API_TOKEN, APP_ID)
    bot.run()

