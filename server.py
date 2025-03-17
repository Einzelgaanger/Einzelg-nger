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
        self.loop = None
    
    def set_event_loop(self, loop):
        """Set the event loop to use for async calls"""
        self.loop = loop
    
    async def broadcast_message(self, message_data):
        """Send a message to all connected clients"""
        if not connected_clients:
            return
            
        message = json.dumps(message_data)
        await asyncio.gather(
            *[client.send(message) for client in connected_clients],
            return_exceptions=True  # Don't let one failed client crash all sends
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
        global bot
        if not bot:
            return
            
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
    
    # Callback functions for the bot
    def status_change_callback(self, bot):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast_status(bot), self.loop)
    
    def sequence_change_callback(self, bot):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast_sequence(bot), self.loop)
    
    def log_callback(self, message, level="info"):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast_log(message, level), self.loop)
    
    def trade_update_callback(self, contract_data):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast_trade(contract_data), self.loop)

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
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=30)
                # Handle any commands from the web UI here
                data = json.loads(message)
                await websocket.send(json.dumps({
                    "type": "echo",
                    "data": data
                }))
            except asyncio.TimeoutError:
                # Send a ping to keep connection alive
                try:
                    pong_waiter = await websocket.ping()
                    await asyncio.wait_for(pong_waiter, timeout=10)
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    # No response to ping, connection probably dead
                    break
    
    except websockets.exceptions.ConnectionClosed:
        logging.info(f"Client disconnected: {client_ip}")
    except Exception as e:
        logging.error(f"Error in WebSocket handler: {str(e)}")
    finally:
        # Unregister client
        if websocket in connected_clients:
            connected_clients.remove(websocket)

# Function to run the bot in a separate thread
def run_bot(api_token, app_id, observer_callbacks):
    """Run the trading bot in a separate thread"""
    global bot
    
    try:
        bot = DerivBinaryOptionsBot(api_token, app_id)
        bot.set_observer_callbacks(observer_callbacks)
        bot.run()
    except Exception as e:
        logging.error(f"Bot thread error: {str(e)}")

# Main function to start the server
async def main():
    """Main function to start the WebSocket server and bot"""
    global bot_thread
    
    # Create observer
    observer = BotObserver()
    
    # Set event loop for callbacks
    observer.set_event_loop(asyncio.get_event_loop())
    
    # Define observer callbacks
    observer_callbacks = {
        'status_change': observer.status_change_callback,
        'sequence_change': observer.sequence_change_callback,
        'log': observer.log_callback,
        'trade_update': observer.trade_update_callback
    }
    
    # Start WebSocket server
    server_host = 'localhost'
    server_port = 8765
    
    logging.info(f"Starting WebSocket server on {server_host}:{server_port}")
    
    # Start the server with ping_interval and ping_timeout
    server = await websockets.serve(
        handler, server_host, server_port,
        ping_interval=20,
        ping_timeout=30,
        max_size=10485760  # 10MB max message size
    )
    
    logging.info("WebSocket server started")
    
    # Start bot in separate thread
    API_TOKEN = "YOUR_ACTUAL_API_TOKEN_HERE"  # Replace with a valid API token
    APP_ID = "1089"  # Your app ID
    
    logging.info("Starting trading bot")
    
    bot_thread = threading.Thread(
        target=run_bot,
        args=(API_TOKEN, APP_ID, observer_callbacks)
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