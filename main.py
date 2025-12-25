# v2v_simulation.py
import streamlit as st
import pandas as pd
import random, uuid, math, hashlib
from dataclasses import dataclass, field
from typing import List, Dict
import altair as alt
import numpy as np

# ==========================================
# 1. SETUP PAGE AND INTRODUCTION
# ==========================================
st.set_page_config(page_title="Future EV Power Sharing Simulation", layout="wide")
st.title("🚗 Future Electric Vehicle Power Sharing Dashboard")

st.markdown("""
### **What is this?**
This dashboard simulates a future highway where electric vehicles (EVs) can **share battery power wirelessly** while driving.
- **Buyers**: Cars running low on battery.
- **Sellers**: Cars with extra energy to sell.
- **The Goal**: See how cars trade energy automatically using a smart network.
""")

# ==========================================
# 2. SIMULATION CONTROLS (Sidebar)
# ==========================================
st.sidebar.header("⚙️ Simulation Settings")
number_of_cars = st.sidebar.slider("Number of Cars on Road", 6, 40, 32, help="How many vehicles are participating in the simulation.")
simulation_duration = st.sidebar.slider("Simulation Duration", 5, 200, 120, help="How long the simulation runs (in rounds).")
high_speed_network = st.sidebar.checkbox("Enable High-Speed 5G Network", True, help="If checked, the network is faster (lower latency).")
simulation_seed = st.sidebar.number_input("Random Seed (for reproducibility)", 0, 99999, 1234)
run_button = st.sidebar.button("🚀 Run Simulation", type="primary")

inductive_range_meters = 3  # Cars must be within 3 meters to charge

# ==========================================
# 3. DEFINE THE "VEHICLE" BLOCKS
# ==========================================
@dataclass
class ElectricVehicle:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    current_battery_kwh: float = 50.0
    total_capacity_kwh: float = 75.0
    role: str = "neutral"  # Can be 'buyer', 'seller', or 'neutral'
    asking_price: float = 0.20
    max_charge_speed: float = 5.0
    position_on_road: float = 0.0
    current_speed_kmh: float = 40.0
    
    # Internal brain for learning price history (Reinforcement Learning light)
    price_memory: Dict[float,float] = field(default_factory=dict)
    possible_prices: List[float] = field(default_factory=lambda:[0.08,0.12,0.16,0.20,0.25,0.30])
    exploration_rate: float = 0.15
    
    def decide_buying_or_selling(self):
        # Step 1: Check Battery Level (State of Charge)
        battery_percentage = self.current_battery_kwh / self.total_capacity_kwh
        
        # Step 2: Decide Role
        if battery_percentage < 0.40:
            self.role = 'buyer'  # "I need power!"
        elif battery_percentage > 0.60:
            self.role = 'seller' # "I have extra power to sell."
        else:
            self.role = 'neutral' # "I'm good for now."

    def set_price_strategy(self):
        # Initialize memory if empty
        for p in self.possible_prices:
            if p not in self.price_memory:
                self.price_memory[p] = 0.0
        
        # Randomly try a new price sometimes (Exploration)
        if random.random() < self.exploration_rate:
            self.asking_price = random.choice(self.possible_prices)
        else:
            # Otherwise, pick the best known price (Exploitation)
            best_value = max(self.price_memory.values())
            candidates = [p for p,v in self.price_memory.items() if v == best_value]
            self.asking_price = random.choice(candidates)

# ==========================================
# 4. HELPER FUNCTIONS (The "Physics" of the world)
# ==========================================
def calculate_alignment_score(distance_gap, side_offset, relative_speed_diff, max_range=3):
    """
    Calculates how well two cars are aligned for charging.
    Returns a score from 0.0 (No connection) to 1.0 (Perfect connection).
    """
    score = 0.95
    
    # Penalty if too far apart
    if distance_gap < 0.1 or distance_gap > max_range:
        score *= 0.2
    else:
        # Optimal charging is in the middle of the range
        score *= math.exp(-((distance_gap - max_range/2)**2)/(2*(0.8**2)))
        
    # Penalty if not in the same lane (lateral offset)
    score *= math.exp(-(side_offset**2)/(2*(0.15**2)))
    
    # Penalty if speeds are too different
    score *= math.exp(-abs(relative_speed_diff)/50.0)
    
    return max(0.0, min(1.0, score))

def get_network_latency(is_fast_network): 
    # Simulate network delay (milliseconds)
    base_latency = 30 if is_fast_network else 80
    jitter = random.gauss(0,15)
    return max(5, base_latency + jitter)

# ==========================================
# 5. MAIN SIMULATION ENGINE
# ==========================================
def start_simulation(n_cars, n_rounds, use_fast_net, sim_seed):
    random.seed(sim_seed)
    np.random.seed(sim_seed)
    
    road_length_meters = 800.0
    fleet = []
    
    # Initialize our fleet of cars
    for _ in range(n_cars):
        capacity = random.choice([60.0, 75.0, 90.0])
        initial_charge = random.uniform(0.12, 0.96) # 12% to 96% charged
        
        new_car = ElectricVehicle(
            current_battery_kwh = initial_charge * capacity,
            total_capacity_kwh = capacity,
            asking_price = random.choice([0.10,0.12,0.14,0.16,0.18,0.20,0.22,0.24,0.26]),
            max_charge_speed = random.choice([3.0,5.0,7.0]),
            position_on_road = random.uniform(0, road_length_meters),
            current_speed_kmh = random.uniform(20, 80)
        )
        fleet.append(new_car)
    
    transaction_ledger = []
    detailed_logs = []
    
    # --- START THE LOOP (Round by Round) ---
    for r in range(n_rounds):
        
        # 1. Every car makes a decision
        for car in fleet:
            car.decide_buying_or_selling()
            car.set_price_strategy()
        
        # 2. Group them
        active_buyers = [c for c in fleet if c.role == 'buyer']
        active_sellers = [c for c in fleet if c.role == 'seller']
        
        # Sort to prioritize best offers
        active_buyers.sort(key=lambda x: x.asking_price, reverse=True) # Highest bidder first
        active_sellers.sort(key=lambda x: x.asking_price)              # Lowest seller first
        
        # 3. Matchmaking logic
        b_idx, s_idx = 0, 0
        while b_idx < len(active_buyers) and s_idx < len(active_sellers):
            buyer = active_buyers[b_idx]
            seller = active_sellers[s_idx]
            
            # Price Negotiation
            if buyer.asking_price < seller.asking_price: 
                # No deal! Price gap too wide.
                b_idx += 1
                continue
            
            # Physics Check: Are they close enough?
            distance_gap = abs(buyer.position_on_road - seller.position_on_road)
            if distance_gap > inductive_range_meters:
                b_idx += 1; s_idx += 1
                continue
            
            # Detailed Physics simulation
            lateral_offset = random.gauss(0, 0.1)
            speed_diff = abs(buyer.current_speed_kmh - seller.current_speed_kmh)
            alignment_quality = calculate_alignment_score(distance_gap, lateral_offset, speed_diff)
            
            # Execute Transaction
            network_delay = get_network_latency(use_fast_net)
            final_price = (buyer.asking_price + seller.asking_price) / 2.0
            
            # Calculate energy transfer efficiency
            # Efficiency drops if alignment is poor or cars are far apart
            efficiency = max(0, alignment_quality * (1 - distance_gap/inductive_range_meters))
            
            # Determine how much energy is actually moved
            energy_moved = max(0.1, efficiency * min(
                buyer.max_charge_speed, 
                seller.max_charge_speed, 
                max(0, 0.4 * buyer.total_capacity_kwh - buyer.current_battery_kwh), # Don't overcharge
                max(0, seller.current_battery_kwh - 0.6 * seller.total_capacity_kwh)  # Don't drain seller
            ))
            
            transfer_successful = energy_moved > 0
            
            if transfer_successful:
                # Update Batteries
                buyer.current_battery_kwh += energy_moved
                seller.current_battery_kwh -= energy_moved
                
                # Record the deal
                total_cost = final_price * energy_moved
                
                record = {
                    'buyer_id': buyer.id,
                    'seller_id': seller.id,
                    'energy_kwh': energy_moved,
                    'price_per_kwh': final_price,
                    'total_cost': total_cost,
                    'round': r,
                    'latency_ms': network_delay,
                    'distance_gap_m': distance_gap,
                    'alignment_quality': alignment_quality
                }
                
                # Generate a unique secure hash for the transaction (Blockchain style)
                tx_hash = hashlib.sha256(str(record).encode()).hexdigest()[:12]
                record['tx_hash'] = tx_hash
                
                transaction_ledger.append(record)
                detailed_logs.append({**record, 'success': True})
            else:
                detailed_logs.append({
                    'buyer_id': buyer.id,
                    'seller_id': seller.id,
                    'energy_kwh': energy_moved,
                    'price_per_kwh': final_price,
                    'round': r,
                    'success': False,
                    'distance_gap_m': distance_gap,
                    'latency_ms': network_delay
                })
            
            # Move to next pair
            b_idx += 1; s_idx += 1
            
        # 4. Log cars that found no match
        matched_buyers = {tx['buyer_id'] for tx in transaction_ledger}
        matched_sellers = {tx['seller_id'] for tx in transaction_ledger}

        for b in active_buyers:
            if b.id not in matched_buyers:
                detailed_logs.append({'buyer_id': b.id, 'energy_kwh': 0, 'round': r, 'success': False, 'reason': 'no_seller_found'})

        for s in active_sellers:
            if s.id not in matched_sellers:
                detailed_logs.append({'seller_id': s.id, 'energy_kwh': 0, 'round': r, 'success': False, 'reason': 'no_buyer_found'})

        # 5. Move all cars forward (Traffic Simulation)
        for car in fleet:
            time_step = 0.01 # small time increment
            # Position = Position + Speed * Time
            car.position_on_road = (car.position_on_road + car.current_speed_kmh * 1000/3600 * time_step) % road_length_meters
    
    # Final cleanup of data for charts
    df_logs = pd.DataFrame(detailed_logs)
    df_fleet = pd.DataFrame([{
        'id': c.id,
        'battery_percentage': c.current_battery_kwh / c.total_capacity_kwh,
        'current_battery_kwh': c.current_battery_kwh,
        'total_capacity_kwh': c.total_capacity_kwh,
        'asking_price': c.asking_price,
        'position_m': c.position_on_road,
        'speed_kmh': c.current_speed_kmh
    } for c in fleet])
    
    df_ledger = pd.DataFrame(transaction_ledger)
    return df_logs, df_fleet, df_ledger

# ==========================================
# 6. RUN BUTTON PRESSED? EXECUTE!
# ==========================================
if run_button:
    with st.spinner("Simulating the Future of Highways..."):
        df_logs, df_fleet, df_ledger = start_simulation(number_of_cars, simulation_duration, high_speed_network, simulation_seed)
    
    st.success("Simulation Complete! Analyzing Data...")
    
    # --- Calculate key stats for the dashboard ---
    # 1. Total Energy
    if 'success' in df_logs.columns and not df_logs.empty and 'energy_kwh' in df_logs.columns:
        df_energy_timeline = df_logs[df_logs['success']==True].groupby('round', as_index=False)['energy_kwh'].sum()
    else:
        df_energy_timeline = pd.DataFrame({'round':[], 'energy_kwh':[]})
        
    total_energy_shared = df_energy_timeline['energy_kwh'].sum() if not df_energy_timeline.empty else 0
    
    # 2. Total Deals
    total_deals_count = len(df_logs[df_logs.get('success', [])==True])
    
    # 3. Network Speed
    avg_network_delay = df_logs['latency_ms'].mean() if 'latency_ms' in df_logs else 0

    # DISPLAY METRICS
    st.markdown("### 📊 Key Results")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Energy Shared", f"{total_energy_shared:.2f} kWh", delta="Real-time")
    col2.metric("Successful Deals", f"{total_deals_count}", "Transactions Completed")
    col3.metric("Avg Network Speed", f"{avg_network_delay:.1f} ms", "Latency Delay")

    st.markdown("---")

    # DISPLAY CHARTS
    st.header("📈 Visual Analysis")

    # Chart 1: Energy over time
    chart_energy = alt.Chart(df_energy_timeline).mark_line(point=True, color='#FF6B6B').encode(
        x=alt.X('round:Q', title='Simulation Time (Rounds)'),
        y=alt.Y('energy_kwh:Q', title='Energy Shared (kWh)'),
        tooltip=['round','energy_kwh']
    ).properties(height=300, width=600, title="⚡ Energy Exchanged Over Time")
    st.altair_chart(chart_energy, use_container_width=True)
    
    # Chart 2: Network Latency
    if 'latency_ms' in df_logs.columns and not df_logs['latency_ms'].dropna().empty:
        st.markdown("###### 📶 5G Network Speed Distribution")
        chart_latency = alt.Chart(df_logs).mark_bar(color='#4ECDC4').encode(
            alt.X('latency_ms:Q', bin=alt.Bin(maxbins=30), title='Network Delay (milliseconds)'),
            y=alt.Y('count()', title='Number of Transactions')
        ).properties(height=200, width=450, title="📶 5G Network Speed Distribution").configure_title(offset=20)
        st.altair_chart(chart_latency, use_container_width=True)
    
    # Chart 3: Live Map
    df_fleet['visual_jitter'] = np.random.uniform(0, 10, len(df_fleet))
    chart_map = alt.Chart(df_fleet).mark_circle(size=100).encode(
        x=alt.X('position_m:Q', title='Car Position on Road (meters)'),
        y=alt.Y('visual_jitter:Q', title='', axis=None),
        color=alt.Color('battery_percentage:Q', scale=alt.Scale(scheme='redyellowgreen'), title='Battery %'),
        tooltip=[alt.Tooltip('id', title='Car ID'), alt.Tooltip('battery_percentage', format='.1%', title='Battery Level')]
    ).properties(height=180, width=800, title="🚗 Live Vehicle Map (Color = Battery Level)")
    st.altair_chart(chart_map, use_container_width=True)
    
    # EXPORT SECTION
    st.markdown("---")
    st.subheader("📥 Download Data")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download Energy Data (CSV)", data=df_energy_timeline.to_csv(index=False), file_name="v2v_energy.csv", mime="text/csv")
    with c2:
        st.download_button("Download Full Logs (CSV)", data=df_logs.to_csv(index=False), file_name="v2v_logs.csv", mime="text/csv")
    with c3:
        st.download_button("Download Vehicle Fleet (CSV)", data=df_fleet.to_csv(index=False), file_name="v2v_fleet.csv", mime="text/csv")

    # DETAILED DATA TABLE
    with st.expander("🔎 View Detailed Simulation Records (Advanced)"):
        st.write("### Transaction Log (All Attempts)")
        st.dataframe(df_logs)
        
        if not df_ledger.empty:
            st.write("### Ledger (Successful Payments Only)")
            st.dataframe(df_ledger)
            st.download_button("Download Ledger (CSV)", data=df_ledger.to_csv(index=False), file_name="v2v_ledger.csv", mime="text/csv")

else:
    st.info("👈 **Start Here**: Adjust the settings in the sidebar and click 'Run Simulation' to see the results!")
