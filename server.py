import asyncio
import websockets
import json
import logging
import time
import random
import threading
from datetime import datetime

# Import your bot file
from bot import DerivBinaryOptionsBot

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_server.log"),
        logging.StreamHandler()
    ]
)

# Global variables
connected_clients = set()
server_running = True
bot = None
bot_thread = None

class BotObserver:
    """Class to observe and relay bot state to connected clients"""
    
    def __init__(self):
        self.last_balance = 100.0  # Default starting balance
    
    async def broadcast_message(self, message_data):
        """Send a message to all connected clients"""
        if not connected_clients:
            return
            
        message = json.dumps(message_data)
        await asyncio.gather(
            *[client.send(message) for client in connected_clients]
        )
    
    async def broadcast_log(self, message, level="info"):
        """Broadcast a log message to all clients"""
        await self.broadcast_message({
            "type": "log",
            "message": message,
            "level": level,
            "timestamp": datetime.now().isoformat()
        })
    
    async def broadcast_status(self, bot):
        """Broadcast bot status to all clients"""
        await self.broadcast_message({
            "type": "status_update",
            "market": bot.current_market,
            "authorized": bot.authorized,
            "is_trading": bot.is_trading,
            "consecutive_losses": bot.consecutive_losses,
            "current_stake": bot.get_current_stake(),
            "stakes": bot.stakes,
            "timestamp": datetime.now().isoformat()
        })
    
    async def broadcast_sequence(self, bot):
        """Broadcast sequence info to all clients"""
        await self.broadcast_message({
            "type": "sequence_update",
            "sequence": bot.sequence,
            "current_trade_index": bot.current_trade_index,
            "timestamp": datetime.now().isoformat()
        })
    
    async def broadcast_trade(self, contract_data):
        """Broadcast trade result to all clients"""
        await self.broadcast_message({
            "type": "trade_update",
            "market": bot.current_market,
            "contract_type": contract_data.get("contract_type", "UNKNOWN"),
            "stake": contract_data.get("buy_price", 0),
            "outcome": contract_data.get("status", "unknown"),
            "profit": contract_data.get("profit", 0),
            "timestamp": datetime.now().isoformat()
        })
        
        # Update balance after trade (in reality would come from actual account)
        profit = float(contract_data.get("profit", 0))
        self.last_balance += profit
        
        await self.broadcast_message({
            "type": "balance_update",
            "balance": self.last_balance,
            "change": profit,
            "timestamp": datetime.now().isoformat()
        })

# Create a modified version of your bot class to handle websocket notifications
class WebsocketDerivBot(DerivBinaryOptionsBot):
    """Modified bot class to send updates to websocket clients"""
    
    def __init__(self, api_token, app_id, observer):
        super().__init__(api_token, app_id)
        self.observer = observer
        
    async def notify_status_change(self):
        """Notify clients about bot status changes"""
        await self.observer.broadcast_status(self)
    
    async def notify_sequence_change(self):
        """Notify clients about sequence changes"""
        await self.observer.broadcast_sequence(self)
    
    async def notify_log(self, message, level="info"):
        """Send log message to clients"""
        await self.observer.broadcast_log(message, level)
    
    # Override methods that need to notify the web interface
    
    def authorize(self):
        """Override to notify when authorization happens"""
        super().authorize()
        asyncio.run(self.notify_log("Authorizing with Deriv API..."))
    
    def select_random_market(self):
        """Override to notify when market selection happens"""
        super().select_random_market()
        asyncio.run(self.notify_log(f"Selected market: {self.current_market}"))
        asyncio.run(self.notify_status_change())
    
    def generate_sequence(self):
        """Override to notify when sequence is generated"""
        super().generate_sequence()
        asyncio.run(self.notify_log(f"Generated sequence: {''.join(self.sequence)}"))
        asyncio.run(self.notify_sequence_change())
    
    def place_trade(self, contract_type):
        """Override to notify when trade is placed"""
        super().place_trade(contract_type)
        asyncio.run(self.notify_log(
            f"Placing {contract_type} trade on {self.current_market} with stake ${self.get_current_stake():.2f}"))
    
    def handle_contract_update(self, contract_data):
        """Override to notify when contract is updated"""
        # Store original status for notification purposes
        original_consecutive_losses = self.consecutive_losses
        
        # Call the original method
        super().handle_contract_update(contract_data)
        
        # If contract is settled, notify clients
        status = contract_data.get("status")
        if status in ["won", "lost"] and contract_data.get("contract_id") == getattr(self.active_contract, "contract_id", None):
            asyncio.run(self.observer.broadcast_trade(contract_data))
            
            profit_text = contract_data.get("profit", "0")
            log_level = "success" if status == "won" else "error"
            asyncio.run(self.notify_log(
                f"Contract {status.upper()}! Profit: {profit_text}", log_level))
            
            # If consecutive losses changed, notify status
            if original_consecutive_losses != self.consecutive_losses:
                asyncio.run(self.notify_status_change())
            
            # If sequence is regenerated, it will call the overridden method

# WebSocket server handler
async def handler(websocket, path):
    """Handle WebSocket connections"""
    global connected_clients, bot
    
    # Register client
    connected_clients.add(websocket)
    client_ip = websocket.remote_address[0]
    logging.info(f"Client connected: {client_ip}")
    
    try:
        # Send initial data if bot is running
        if bot:
            observer = getattr(bot, "observer", None)
            if observer:
                await observer.broadcast_status(bot)
                await observer.broadcast_sequence(bot)
                await observer.broadcast_log("Connected to trading bot server", "success")
        
        # Keep the connection alive
        while True:
            message = await websocket.recv()
            # Handle any commands from the web UI here
            # For now, we're just echoing back
            data = json.loads(message)
            await websocket.send(json.dumps({
                "type": "echo",
                "data": data
            }))
    
    except websockets.exceptions.ConnectionClosed:
        logging.info(f"Client disconnected: {client_ip}")
    finally:
        # Unregister client
        connected_clients.remove(websocket)

# Function to run the bot in a separate thread
def run_bot(api_token, app_id, observer):
    """Run the trading bot in a separate thread"""
    global bot
    
    bot = WebsocketDerivBot(api_token, app_id, observer)
    bot.run()

# Main function to start the server
async def main():
    """Main function to start the WebSocket server and bot"""
    global bot_thread
    
    # Create observer
    observer = BotObserver()
    
    # Start WebSocket server
    server_host = 'localhost'
    server_port = 8765
    
    logging.info(f"Starting WebSocket server on {server_host}:{server_port}")
    
    server = await websockets.serve(
        handler, server_host, server_port
    )
    
    logging.info("WebSocket server started")
    await observer.broadcast_log("WebSocket server started", "info")
    
    # Start bot in separate thread
    API_TOKEN = "8fRRApGnNy0TY6T"  # Your API token
    APP_ID = "1089"  # Your app ID
    
    logging.info("Starting trading bot")
    
    bot_thread = threading.Thread(
        target=run_bot,
        args=(API_TOKEN, APP_ID, observer)
    )
    bot_thread.daemon = True
    bot_thread.start()
    
    logging.info("Trading bot started")
    
    # Keep the server running
    try:
        await server.wait_closed()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logging.info("Server stopping...")
    finally:
        logging.info("Server stopped")

# Run the server
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped by user")
        server_running = False
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        server_running = False