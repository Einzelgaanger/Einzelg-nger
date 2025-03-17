// WebSocket connection
let socket;
let isConnected = false;
let balanceChart;
let balanceData = [];
let balanceLabels = [];
let initialBalance = 100; // You would set this from the actual bot data
let currentBalance = initialBalance;

// Connect to the WebSocket server
function connectToServer() {
    // Change this to match your server address and port
    socket = new WebSocket('ws://localhost:8765');
    
    socket.onopen = function(event) {
        console.log('Connected to server');
        isConnected = true;
        updateConnectionStatus(true);
        logMessage('Connected to the trading bot server', 'success');
    };
    
    socket.onmessage = function(event) {
        const data = JSON.parse(event.data);
        processMessage(data);
    };
    
    socket.onclose = function(event) {
        console.log('Disconnected from server');
        isConnected = false;
        updateConnectionStatus(false);
        logMessage('Connection to server closed. Attempting to reconnect...', 'warning');
        
        // Try to reconnect after 5 seconds
        setTimeout(connectToServer, 5000);
    };
    
    socket.onerror = function(error) {
        console.error('WebSocket error:', error);
        logMessage('WebSocket error occurred', 'error');
    };
}

// Update connection status indicator
function updateConnectionStatus(connected) {
    const statusElement = document.getElementById('connection-status');
    const statusDot = document.getElementById('status-dot');
    
    if (connected) {
        statusElement.textContent = 'Connected';
        statusDot.classList.add('connected');
    } else {
        statusElement.textContent = 'Disconnected';
        statusDot.classList.remove('connected');
    }
}

// Process incoming message from the server
function processMessage(data) {
    switch (data.type) {
        case 'status_update':
            updateStatus(data);
            break;
        case 'sequence_update':
            updateSequence(data);
            break;
        case 'trade_update':
            updateTradeHistory(data);
            break;
        case 'balance_update':
            updateBalance(data);
            break;
        case 'log':
            logMessage(data.message, data.level);
            break;
        default:
            console.log('Unknown message type:', data.type);
    }
}

// Update the bot status display
function updateStatus(data) {
    document.getElementById('current-market').textContent = data.market || '--';
    document.getElementById('authorized-status').textContent = data.authorized ? 'Yes' : 'No';
    document.getElementById('trading-status').textContent = data.is_trading ? 'Yes' : 'No';
    document.getElementById('current-round').textContent = data.consecutive_losses + 1 || '1';
    document.getElementById('current-stake').textContent = `$${data.current_stake ? data.current_stake.toFixed(2) : '0.00'}`;
    
    updateStakesDisplay(data.stakes, data.consecutive_losses);
}

// Update the sequence display
function updateSequence(data) {
    const sequenceDisplay = document.getElementById('sequence-display');
    sequenceDisplay.innerHTML = '';
    
    data.sequence.forEach((item, index) => {
        const sequenceItem = document.createElement('div');
        sequenceItem.classList.add('sequence-item', item);
        sequenceItem.textContent = item;
        
        if (index === data.current_trade_index) {
            sequenceItem.classList.add('active');
        }
        
        sequenceDisplay.appendChild(sequenceItem);
    });
}

// Update the stakes display
function updateStakesDisplay(stakes, activeIndex) {
    const stakesInfo = document.getElementById('stakes-info');
    stakesInfo.innerHTML = '';
    
    stakes.forEach((stake, index) => {
        const stakeItem = document.createElement('div');
        stakeItem.classList.add('stake-item');
        
        if (index === activeIndex) {
            stakeItem.classList.add('active');
        }
        
        stakeItem.innerHTML = `
            <div class="stake-round">Round ${index + 1}</div>
            <div class="stake-value">$${stake.toFixed(2)}</div>
        `;
        
        stakesInfo.appendChild(stakeItem);
    });
}

// Update the trade history table
function updateTradeHistory(data) {
  const historyBody = document.getElementById('trade-history-body');
  
  const row = document.createElement('tr');
  
  // Format timestamp
  const timestamp = new Date(data.timestamp).toLocaleTimeString();
  
  // Create outcome class based on win/loss
  const outcomeClass = data.outcome === 'won' ? 'outcome-won' : 'outcome-lost';
  
  // Create profit/loss class and text
  const profitLossClass = parseFloat(data.profit) >= 0 ? 'profit' : 'loss';
  const profitLossText = parseFloat(data.profit) >= 0 
      ? `+$${parseFloat(data.profit).toFixed(2)}` 
      : `-$${Math.abs(parseFloat(data.profit)).toFixed(2)}`;
  
  row.innerHTML = `
      <td>${timestamp}</td>
      <td>${data.market}</td>
      <td>${data.contract_type}</td>
      <td>$${parseFloat(data.stake).toFixed(2)}</td>
      <td class="${outcomeClass}">${data.outcome.toUpperCase()}</td>
      <td class="${profitLossClass}">${profitLossText}</td>
  `;
  
  // Insert at the beginning of the table
  if (historyBody.firstChild) {
      historyBody.insertBefore(row, historyBody.firstChild);
  } else {
      historyBody.appendChild(row);
  }
  
  // Limit the number of rows to 100
  if (historyBody.children.length > 100) {
      historyBody.removeChild(historyBody.lastChild);
  }
}

// Update balance chart
function updateBalance(data) {
  currentBalance = data.balance;
  
  // Add new data point
  const now = new Date();
  const timeLabel = now.toLocaleTimeString();
  
  balanceLabels.push(timeLabel);
  balanceData.push(currentBalance);
  
  // Keep chart data to a reasonable size (last 50 points)
  if (balanceLabels.length > 50) {
      balanceLabels.shift();
      balanceData.shift();
  }
  
  // Update chart
  balanceChart.update();
}

// Add a log message to the log container
function logMessage(message, level = 'info') {
  const logContainer = document.getElementById('log-container');
  const logEntry = document.createElement('div');
  
  logEntry.classList.add('log-entry', level);
  
  // Format timestamp
  const timestamp = new Date().toLocaleTimeString();
  
  logEntry.innerHTML = `<span>[${timestamp}]</span> ${message}`;
  
  // Add the new log entry at the top
  logContainer.insertBefore(logEntry, logContainer.firstChild);
  
  // Limit the number of log entries
  if (logContainer.children.length > 200) {
      logContainer.removeChild(logContainer.lastChild);
  }
}

// Initialize the balance chart
function initBalanceChart() {
  const ctx = document.getElementById('balance-chart').getContext('2d');
  
  balanceChart = new Chart(ctx, {
      type: 'line',
      data: {
          labels: balanceLabels,
          datasets: [{
              label: 'Account Balance',
              data: balanceData,
              backgroundColor: 'rgba(77, 91, 249, 0.2)',
              borderColor: 'rgba(77, 91, 249, 1)',
              borderWidth: 2,
              tension: 0.3,
              fill: true,
              pointRadius: 2,
              pointHoverRadius: 5
          }]
      },
      options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
              legend: {
                  display: false
              },
              tooltip: {
                  callbacks: {
                      label: function(context) {
                          return `$${context.parsed.y.toFixed(2)}`;
                      }
                  }
              }
          },
          scales: {
              x: {
                  grid: {
                      display: false
                  },
                  ticks: {
                      maxTicksLimit: 10,
                      maxRotation: 0
                  }
              },
              y: {
                  beginAtZero: false,
                  ticks: {
                      callback: function(value) {
                          return '$' + value.toFixed(0);
                      }
                  }
              }
          }
      }
  });
}

// Initialize demo data (until real data comes in)
function initDemoData() {
  // Initialize with some demo data
  const demoSequence = ['R', 'G', 'R', 'G', 'R', 'G', 'R', 'G', 'R', 'G'];
  const demoStakes = [0.35, 0.60, 1.61, 4.34, 11.69, 31.49, 84.82, 228.47, 615.40, 1657.63];
  
  // Show demo data in the UI
  updateStatus({
      market: 'R_10',
      authorized: true,
      is_trading: true,
      consecutive_losses: 0,
      current_stake: demoStakes[0],
      stakes: demoStakes
  });
  
  updateSequence({
      sequence: demoSequence,
      current_trade_index: 0
  });
  
  // Add initial balance point
  const now = new Date();
  balanceLabels.push(now.toLocaleTimeString());
  balanceData.push(initialBalance);
  
  // Log initial message
  logMessage('Waiting for connection to trading bot server...', 'info');
}

// Initialize the application
function init() {
  // Initialize the balance chart
  initBalanceChart();
  
  // Initialize with demo data
  initDemoData();
  
  // Connect to the WebSocket server
  connectToServer();
  
  // Set up reconnection mechanism
  window.addEventListener('online', function() {
      if (!isConnected) {
          logMessage('Network connection restored. Reconnecting...', 'info');
          connectToServer();
      }
  });
}

// Start the application when the page loads
window.addEventListener('DOMContentLoaded', init);