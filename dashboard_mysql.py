#!/usr/bin/env python3
"""
Receipt Dashboard - All Business Types
=======================================
Live dashboard with real-time stats for Down Home, Personal, and Music City Rodeo
"""

from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS
import pymysql
import os
from datetime import datetime, date
from decimal import Decimal
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

# MySQL Configuration - uses centralized db_config
def get_mysql_config():
    """Get MySQL config from environment variables."""
    mysql_url = os.environ.get('MYSQL_URL')
    if mysql_url:
        parsed = urlparse(mysql_url)
        return {
            'host': parsed.hostname,
            'port': parsed.port or 3306,
            'user': parsed.username,
            'password': parsed.password,
            'database': parsed.path.lstrip('/') if parsed.path else 'railway',
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor
        }

    # Fallback to individual env vars
    return {
        'host': os.environ.get('MYSQLHOST', 'localhost'),
        'port': int(os.environ.get('MYSQLPORT', '3306')),
        'user': os.environ.get('MYSQLUSER', 'root'),
        'password': os.environ.get('MYSQLPASSWORD', ''),
        'database': os.environ.get('MYSQLDATABASE', 'railway'),
        'charset': 'utf8mb4',
        'cursorclass': pymysql.cursors.DictCursor
    }

MYSQL_CONFIG = get_mysql_config()

# R2 public URL - use env var with fallback
R2_PUBLIC = os.environ.get('R2_PUBLIC_URL', 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev')

def get_db():
    return pymysql.connect(**MYSQL_CONFIG)

def serialize(obj):
    """JSON serializer for objects not serializable by default"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)

# Dashboard HTML template
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Receipt Dashboard - All Businesses</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #eee; }
        .header { background: linear-gradient(135deg, #16213e 0%, #0f3460 100%); padding: 20px; text-align: center; }
        .header h1 { color: #e94560; margin-bottom: 10px; }

        /* Business Type Cards */
        .business-cards { display: flex; justify-content: center; gap: 20px; margin: 15px 0; flex-wrap: wrap; }
        .business-card {
            background: #0f3460; padding: 15px 25px; border-radius: 8px; cursor: pointer;
            border: 2px solid transparent; transition: all 0.2s;
            min-width: 200px; text-align: center;
        }
        .business-card:hover { border-color: #e94560; }
        .business-card.active { border-color: #00ff88; background: #16213e; }
        .business-card .name { font-weight: bold; font-size: 1.1em; margin-bottom: 8px; }
        .business-card .progress-bar { height: 8px; background: #1a1a2e; border-radius: 4px; overflow: hidden; margin: 5px 0; }
        .business-card .progress-fill { height: 100%; background: linear-gradient(90deg, #e94560, #00ff88); transition: width 0.3s; }
        .business-card .stats-row { display: flex; justify-content: space-between; font-size: 0.85em; color: #888; margin-top: 5px; }
        .business-card .pct { font-size: 1.5em; font-weight: bold; }
        .business-card .pct.complete { color: #00ff88; }
        .business-card .pct.partial { color: #ffaa00; }

        .overall-stats { display: flex; justify-content: center; gap: 40px; margin-top: 15px; padding: 10px; background: #0f346055; border-radius: 8px; }
        .stat { text-align: center; }
        .stat-value { font-size: 1.8em; font-weight: bold; color: #00d9ff; }
        .stat-label { font-size: 0.85em; color: #888; }

        .filters { background: #16213e; padding: 15px; display: flex; gap: 15px; justify-content: center; flex-wrap: wrap; }
        .filters input, .filters select { padding: 8px 12px; border: 1px solid #333; border-radius: 4px; background: #1a1a2e; color: #eee; }
        .filters button { padding: 8px 20px; background: #e94560; border: none; border-radius: 4px; color: white; cursor: pointer; }
        .filters button:hover { background: #ff6b8a; }

        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .transaction-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px; }
        .transaction-card { background: #16213e; border-radius: 8px; padding: 15px; border-left: 4px solid #e94560; }
        .transaction-card.verified { border-left-color: #00ff88; }
        .transaction-card.subscription { border-left-color: #00d9ff; }
        .transaction-card.needs_receipt { border-left-color: #ff6b6b; }
        .card-header { display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px; }
        .merchant { font-weight: bold; font-size: 1.1em; color: #fff; }
        .amount { font-size: 1.2em; color: #00d9ff; font-weight: bold; }
        .date { color: #888; font-size: 0.85em; }
        .description { color: #aaa; font-size: 0.9em; margin: 8px 0; font-style: italic; }
        .status-badge { display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 0.75em; text-transform: uppercase; }
        .status-verified { background: #00ff8833; color: #00ff88; }
        .status-subscription { background: #00d9ff33; color: #00d9ff; }
        .status-needs_receipt { background: #ff6b6b33; color: #ff6b6b; }
        .status-no_receipt_needed { background: #88888833; color: #888; }
        .receipt-thumb { width: 100%; height: 120px; object-fit: cover; border-radius: 4px; margin-top: 10px; cursor: pointer; background: #0f3460; }
        .receipt-thumb:hover { opacity: 0.8; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 1000; justify-content: center; align-items: center; }
        .modal.active { display: flex; }
        .modal img { max-width: 90%; max-height: 90%; border-radius: 8px; }
        .modal-close { position: absolute; top: 20px; right: 30px; color: white; font-size: 30px; cursor: pointer; }
        .loading { text-align: center; padding: 50px; color: #888; }
        .no-receipt { color: #ff6b6b; font-size: 0.85em; text-align: center; padding: 15px; background: #ff6b6b22; border-radius: 4px; margin-top: 10px; }
        .auto-refresh { position: fixed; bottom: 20px; right: 20px; background: #16213e; padding: 10px 15px; border-radius: 20px; font-size: 0.85em; }
        .auto-refresh.active { background: #00ff8822; color: #00ff88; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Receipt Dashboard</h1>

        <div class="business-cards" id="businessCards"></div>

        <div class="overall-stats">
            <div class="stat">
                <div class="stat-value" id="totalCount">-</div>
                <div class="stat-label">Transactions</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="totalAmount">-</div>
                <div class="stat-label">Amount</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="verifiedCount">-</div>
                <div class="stat-label">Verified</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="needsReceipt">-</div>
                <div class="stat-label">Need Receipts</div>
            </div>
        </div>
    </div>

    <div class="filters">
        <input type="text" id="searchInput" placeholder="Search merchant...">
        <select id="statusFilter">
            <option value="">All Statuses</option>
            <option value="verified">Verified</option>
            <option value="subscription">Subscription</option>
            <option value="needs_receipt">Needs Receipt</option>
            <option value="no_receipt_needed">No Receipt Needed</option>
        </select>
        <select id="sortBy">
            <option value="date_desc">Newest First</option>
            <option value="date_asc">Oldest First</option>
            <option value="amount_desc">Highest Amount</option>
            <option value="amount_asc">Lowest Amount</option>
        </select>
        <button onclick="loadTransactions()">Refresh</button>
    </div>

    <div class="container">
        <div class="transaction-grid" id="transactionGrid">
            <div class="loading">Loading transactions...</div>
        </div>
    </div>

    <div class="modal" id="imageModal" onclick="closeModal()">
        <span class="modal-close">&times;</span>
        <img id="modalImage" src="">
    </div>

    <div class="auto-refresh" id="autoRefresh">Auto-refresh: <span id="refreshTimer">30s</span></div>

    <script>
        const R2_PUBLIC = '{{ r2_public }}';
        let currentBusiness = 'Down Home';
        let refreshInterval = null;
        let countdown = 30;

        async function loadAllStats() {
            const response = await fetch('/api/all-stats');
            const data = await response.json();

            const cardsHtml = data.businesses.map(b => {
                const pctClass = b.verified_pct >= 100 ? 'complete' : 'partial';
                const isActive = b.name === currentBusiness ? 'active' : '';
                return `
                    <div class="business-card ${isActive}" onclick="selectBusiness('${b.name}')">
                        <div class="name">${b.name}</div>
                        <div class="pct ${pctClass}">${b.verified_pct.toFixed(1)}%</div>
                        <div class="progress-bar"><div class="progress-fill" style="width: ${b.verified_pct}%"></div></div>
                        <div class="stats-row">
                            <span>${b.verified}/${b.need_receipts} verified</span>
                            <span>$${b.amount.toLocaleString()}</span>
                        </div>
                    </div>
                `;
            }).join('');

            document.getElementById('businessCards').innerHTML = cardsHtml;
        }

        async function loadTransactions() {
            const search = document.getElementById('searchInput').value;
            const status = document.getElementById('statusFilter').value;
            const sort = document.getElementById('sortBy').value;

            const params = new URLSearchParams();
            params.append('business', currentBusiness);
            if (search) params.append('search', search);
            if (status) params.append('status', status);
            params.append('sort', sort);

            const response = await fetch('/api/transactions?' + params);
            const data = await response.json();

            // Update stats
            document.getElementById('totalCount').textContent = data.total.toLocaleString();
            document.getElementById('totalAmount').textContent = '$' + data.totalAmount.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0});
            document.getElementById('verifiedCount').textContent = data.verified + '/' + data.needReceipts;
            document.getElementById('needsReceipt').textContent = data.needReceipts - data.verified;

            // Render transactions
            const grid = document.getElementById('transactionGrid');
            if (data.transactions.length === 0) {
                grid.innerHTML = '<div class="loading">No transactions found</div>';
            } else {
                grid.innerHTML = data.transactions.map(tx => renderTransaction(tx)).join('');
            }

            // Reload business cards
            loadAllStats();

            // Reset countdown
            countdown = 30;
        }

        function selectBusiness(name) {
            currentBusiness = name;
            loadTransactions();
        }

        function renderTransaction(tx) {
            const status = tx.receipt_validation_status || 'needs_receipt';
            let statusClass = '';
            if (status === 'verified') statusClass = 'verified';
            else if (status === 'subscription') statusClass = 'subscription';
            else if (status === 'needs_receipt') statusClass = 'needs_receipt';

            let receiptHtml = '';
            const r2Url = tx.r2_url || tx.receipt_url;
            if (r2Url) {
                const fullUrl = r2Url.startsWith('http') ? r2Url : R2_PUBLIC + '/' + r2Url;
                if (r2Url.endsWith('.pdf')) {
                    receiptHtml = '<a href="' + fullUrl + '" target="_blank" class="no-receipt" style="background:#e94560;color:white;">View PDF</a>';
                } else {
                    receiptHtml = '<img class="receipt-thumb" src="' + fullUrl + '" onclick="showImage(\\'' + fullUrl + '\\')" onerror="this.style.display=\\'none\\'">';
                }
            } else if (status !== 'no_receipt_needed') {
                receiptHtml = '<div class="no-receipt">NEEDS RECEIPT</div>';
            }

            return `
                <div class="transaction-card ${statusClass}">
                    <div class="card-header">
                        <div>
                            <div class="merchant">${tx.chase_description || 'Unknown'}</div>
                            <div class="date">${tx.chase_date || ''}</div>
                        </div>
                        <div class="amount">$${Math.abs(tx.chase_amount || 0).toFixed(2)}</div>
                    </div>
                    ${tx.mi_description ? '<div class="description">' + tx.mi_description + '</div>' : ''}
                    <span class="status-badge status-${status}">${status.replace('_', ' ')}</span>
                    ${receiptHtml}
                </div>
            `;
        }

        function showImage(url) {
            event.stopPropagation();
            document.getElementById('modalImage').src = url;
            document.getElementById('imageModal').classList.add('active');
        }

        function closeModal() {
            document.getElementById('imageModal').classList.remove('active');
        }

        // Auto refresh every 30 seconds
        function startAutoRefresh() {
            refreshInterval = setInterval(() => {
                countdown--;
                document.getElementById('refreshTimer').textContent = countdown + 's';
                if (countdown <= 0) {
                    loadTransactions();
                }
            }, 1000);
            document.getElementById('autoRefresh').classList.add('active');
        }

        // Load on page load
        loadAllStats();
        loadTransactions();
        startAutoRefresh();
    </script>
</body>
</html>
'''

@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML, r2_public=R2_PUBLIC)

@app.route('/api/all-stats')
def get_all_stats():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            business_type,
            COUNT(*) as total,
            SUM(ABS(chase_amount)) as amount,
            SUM(CASE WHEN receipt_validation_status = 'no_receipt_needed' THEN 1 ELSE 0 END) as no_need,
            SUM(CASE WHEN receipt_validation_status IN ('verified', 'subscription')
                AND (r2_url IS NOT NULL OR receipt_url IS NOT NULL) THEN 1 ELSE 0 END) as verified
        FROM transactions
        WHERE business_type IS NOT NULL
        GROUP BY business_type
        ORDER BY COUNT(*) DESC
    """)

    businesses = []
    for row in cursor.fetchall():
        total = row['total'] or 0
        no_need = row['no_need'] or 0
        verified = row['verified'] or 0
        need_receipts = total - no_need
        pct = (verified / need_receipts * 100) if need_receipts > 0 else 100

        businesses.append({
            'name': row['business_type'],
            'total': total,
            'amount': float(row['amount'] or 0),
            'no_need': no_need,
            'need_receipts': need_receipts,
            'verified': verified,
            'verified_pct': round(pct, 1)
        })

    conn.close()
    return jsonify({'businesses': businesses})

@app.route('/api/transactions')
def get_transactions():
    business = request.args.get('business', 'Down Home')
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    sort = request.args.get('sort', 'date_desc')
    limit = int(request.args.get('limit', 500))

    conn = get_db()
    cursor = conn.cursor()

    # Build query
    query = """
        SELECT _index, chase_description, chase_amount, chase_date,
               receipt_url, r2_url, mi_description, receipt_validation_status,
               ocr_merchant, ocr_amount, business_type
        FROM transactions
        WHERE business_type = %s
    """
    params = [business]

    if search:
        query += " AND chase_description LIKE %s"
        params.append(f'%{search}%')

    if status:
        query += " AND receipt_validation_status = %s"
        params.append(status)

    # Sorting
    if sort == 'date_desc':
        query += " ORDER BY chase_date DESC"
    elif sort == 'date_asc':
        query += " ORDER BY chase_date ASC"
    elif sort == 'amount_desc':
        query += " ORDER BY ABS(chase_amount) DESC"
    elif sort == 'amount_asc':
        query += " ORDER BY ABS(chase_amount) ASC"

    query += f" LIMIT {limit}"

    cursor.execute(query, params)
    transactions = cursor.fetchall()

    # Get stats for this business
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(ABS(chase_amount)) as total_amount,
            SUM(CASE WHEN receipt_validation_status = 'no_receipt_needed' THEN 1 ELSE 0 END) as no_need,
            SUM(CASE WHEN receipt_validation_status IN ('verified', 'subscription')
                AND (r2_url IS NOT NULL OR receipt_url IS NOT NULL) THEN 1 ELSE 0 END) as verified
        FROM transactions WHERE business_type = %s
    """, (business,))
    stats = cursor.fetchone()

    conn.close()

    # Serialize transactions
    serialized = []
    for tx in transactions:
        row = {}
        for key, value in tx.items():
            row[key] = serialize(value) if value is not None else None
        serialized.append(row)

    total = stats['total'] or 0
    no_need = stats['no_need'] or 0
    verified = stats['verified'] or 0
    need_receipts = total - no_need

    return jsonify({
        'transactions': serialized,
        'total': total,
        'totalAmount': float(stats['total_amount'] or 0),
        'verified': verified,
        'needReceipts': need_receipts,
        'verifiedPct': round(verified / need_receipts * 100, 1) if need_receipts > 0 else 100
    })

@app.route('/api/stats')
def get_stats():
    business = request.args.get('business', 'Down Home')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            receipt_validation_status,
            COUNT(*) as count,
            SUM(chase_amount) as amount
        FROM transactions
        WHERE business_type = %s
        GROUP BY receipt_validation_status
        ORDER BY count DESC
    """, (business,))
    by_status = cursor.fetchall()

    conn.close()

    return jsonify({
        'byStatus': [{**s, 'amount': float(s['amount'] or 0)} for s in by_status]
    })

@app.route('/api/transaction/<int:tx_id>')
def get_transaction(tx_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM transactions WHERE _index = %s
    """, (tx_id,))
    tx = cursor.fetchone()
    conn.close()

    if not tx:
        return jsonify({'error': 'Not found'}), 404

    serialized = {}
    for key, value in tx.items():
        serialized[key] = serialize(value) if value is not None else None

    return jsonify(serialized)

if __name__ == '__main__':
    print("=" * 60)
    print("RECEIPT DASHBOARD - ALL BUSINESSES")
    print("=" * 60)
    print(f"MySQL: {MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}")
    print(f"R2: {R2_PUBLIC}")
    print("-" * 60)
    print("Starting server on http://localhost:8888")
    print("Auto-refresh: 30 seconds")
    print("=" * 60)
    app.run(host='0.0.0.0', port=8888, debug=False)
