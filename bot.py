import websocket
import json
import threading
import time
import random
import logging
import sys
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
        self.trade_duration = 1  # 1 minute
        self.trade_duration_unit = "m"  # minutes
        self.sequence = []  # Sequence of trades (R/G)
        self.current_trade_index = 0
        
        # Predefined stakes for each round
        self.stakes = [
            0.35,      # Round 1
            0.60,      # Round 2
            1.61,      # Round 3
            4.34,      # Round 4
            11.69,     # Round 5
            31.49,     # Round 6
            84.82,     # Round 7
            228.47,    # Round 8
            615.40,    # Round 9
            1657.63    # Round 10
        ]
        self.max_consecutive_losses = len(self.stakes)
        self.consecutive_losses = 0
        
        # Trading state
        self.is_trading = False
        self.waiting_for_contract_settlement = False
        
        # For observer pattern
        self.observer_callbacks = {
            'status_change': None,
            'sequence_change': None,
            'log': None,
            'trade_update': None
        }
    
    def set_observer_callbacks(self, callbacks):
        """Set observer callbacks for events"""
        self.observer_callbacks.update(callbacks)
    
    def notify_status_change(self):
        """Notify about status changes"""
        if self.observer_callbacks['status_change']:
            self.observer_callbacks['status_change'](self)
    
    def notify_sequence_change(self):
        """Notify about sequence changes"""
        if self.observer_callbacks['sequence_change']:
            self.observer_callbacks['sequence_change'](self)
    
    def notify_log(self, message, level="info"):
        """Send log message"""
        if self.observer_callbacks['log']:
            self.observer_callbacks['log'](message, level)
        logging.log(
            logging.INFO if level == "info" else 
            logging.ERROR if level == "error" else
            logging.WARNING if level == "warning" else
            logging.INFO, 
            message
        )
    
    def notify_trade_update(self, contract_data):
        """Notify about trade updates"""
        if self.observer_callbacks['trade_update']:
            self.observer_callbacks['trade_update'](contract_data)
    
    def get_next_req_id(self):
        """Get the next request ID and increment counter"""
        req_id = self.req_id
        self.req_id += 1
        return req_id
    
    def connect(self):
        """Establish WebSocket connection"""
        self.notify_log("Connecting to Deriv API...")
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
        self.notify_log("WebSocket connection opened")
        self.authorize()
    
    def on_message(self, ws, message):
        """Handle incoming messages"""
        data = json.loads(message)
        msg_type = data.get('msg_type')
        
        try:
            # Handle authorization
            if msg_type == 'authorize' and data.get('authorize'):
                self.authorized = True
                self.notify_log("Successfully authorized with Deriv API", "success")
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
                self.notify_log(f"API Error: {error_message} (Code: {error_code})", "error")
                
                # Check if error is insufficient balance
                if "balance" in error_message.lower() and "insufficient" in error_message.lower():
                    self.notify_log("Insufficient balance. Exiting program.", "error")
                    self.ws.close()
                    sys.exit(1)
                
                # If market is closed, try the next market
                if "market is closed" in error_message.lower() or "market" in error_message.lower():
                    self.notify_log(f"Market {self.current_market} is closed. Trying next market.", "warning")
                    self.select_random_market()
                    self.start_trading_sequence()
        
        except Exception as e:
            self.notify_log(f"Error processing message: {str(e)}", "error")
    
    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        self.notify_log(f"WebSocket Error: {error}", "error")
    
    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection closure"""
        self.notify_log(f"WebSocket connection closed: {close_status_code} - {close_msg}", "warning")
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
            self.notify_log("No active markets available", "error")
            sys.exit(1)
        
        self.current_market = random.choice(self.active_markets)
        self.notify_log(f"Selected market: {self.current_market}")
        self.notify_status_change()
    
    def generate_sequence(self):
        """Generate a random sequence of trades (R/G)"""
        self.sequence = random.choices(['R', 'G'], k=10)
        self.notify_log(f"Generated sequence: {''.join(self.sequence)}")
        self.current_trade_index = 0
        self.notify_sequence_change()
    
    def get_current_stake(self):
        """Get the stake for the current loss streak"""
        if self.consecutive_losses >= len(self.stakes):
            self.notify_log(f"Reached maximum consecutive losses ({self.max_consecutive_losses}). Exiting program.", "error")
            self.ws.close()
            sys.exit(1)
        
        return self.stakes[self.consecutive_losses]
    
    def start_trading_sequence(self):
        """Start trading sequence"""
        if not self.authorized or not self.current_market:
            self.notify_log("Not authorized or no market selected", "error")
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
            self.notify_log("Reached end of sequence. Generating new sequence.", "warning")
            self.generate_sequence()
        
        # Get the next trade type
        trade_type = self.sequence[self.current_trade_index]
        contract_type = "PUT" if trade_type == 'R' else "CALL"
        
        self.place_trade(contract_type)
    
    def place_trade(self, contract_type):
        """Place a binary options trade"""
        if not self.authorized or not self.current_market:
            self.notify_log("Cannot place trade: Not authorized or no market selected", "error")
            return
        
        current_stake = self.get_current_stake()
        
        # Log trade details
        self.notify_log(f"Placing {contract_type} trade on {self.current_market} with stake ${current_stake:.2f}")
        
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
            self.notify_log(f"Contract placed successfully. ID: {contract_id}", "success")
            
            # Subscribe to contract updates
            subscription_req_id = self.get_next_req_id()
            self.ws.send(json.dumps({
                "proposal_open_contract": 1,
                "contract_id": contract_id,
                "subscribe": 1,
                "req_id": subscription_req_id
            }))
        else:
            self.notify_log(f"Failed to place contract. Request ID: {req_id}", "error")
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
        
        # Notify observer of trade update
        self.notify_trade_update(contract_data)
        
        if status == "won":
            profit = contract_data.get("profit")
            self.notify_log(f"Contract won! Profit: {profit}", "success")
            
            # Reset for new trading sequence
            self.consecutive_losses = 0
            self.select_random_market()
            self.generate_sequence()
            self.start_trading_sequence()
            
        elif status == "lost":
            loss = contract_data.get("profit")
            self.notify_log(f"Contract lost. Loss: {loss}", "error")
            
            # Increment consecutive losses and trade index
            self.consecutive_losses += 1
            self.current_trade_index += 1
            
            # Check if we reached the end of the sequence
            if self.current_trade_index >= len(self.sequence):
                self.notify_log("Reached end of sequence. Generating new sequence.")
                self.generate_sequence()
            
            # Check if we've reached maximum losses
            if self.consecutive_losses >= len(self.stakes):
                self.notify_log(f"Reached maximum consecutive losses ({self.max_consecutive_losses}). Exiting program.", "error")
                self.ws.close()
                sys.exit(1)
            
            # Log information about the next stake
            next_stake = self.stakes[self.consecutive_losses]
            self.notify_log(f"Moving to round {self.consecutive_losses + 1} with stake: {next_stake}")
            
            # Update status after consecutive losses change
            self.notify_status_change()
            
            # Place next trade immediately
            self.place_next_trade()
        
        # Clear active contract
        self.active_contract = None
    
    def run(self):
        """Main bot loop"""
        self.notify_log("Starting Deriv Binary Options Trading Bot", "info")
        self.notify_log("Using synthetic indices markets")
        
        self.connect()
        
        try:
            # Keep the thread alive
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            self.notify_log("Bot stopped by user")
            if self.ws:
                self.ws.close()
        except Exception as e:
            self.notify_log(f"Unexpected error: {str(e)}", "error")
            if self.ws:
                self.ws.close()

# Only execute if this file is run directly
if __name__ == "__main__":
    API_TOKEN = "8fRRApGnNy0TY6T"  # Your API token
    APP_ID = "1089"  # Your app ID
    
    bot = DerivBinaryOptionsBot(API_TOKEN, APP_ID)
    bot.run()
    
