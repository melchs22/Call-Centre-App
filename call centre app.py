import streamlit as st
import mysql.connector
import pandas as pd
import plotly.express as px
from datetime import datetime
import httpx
from httpx_oauth.clients.google import GoogleOAuth2
import os


# Database initialization
def init_db():
    conn = mysql.connector.connect(
        host=st.secrets["mysql"]["host"],
        port=st.secrets["mysql"]["port"],
        database=st.secrets["mysql"]["database"],
        user=st.secrets["mysql"]["user"],
        password=st.secrets["mysql"]["password"]
    )
    c = conn.cursor()
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (email VARCHAR(255) PRIMARY KEY, role VARCHAR(50))''')
    # KPIs table
    c.execute('''CREATE TABLE IF NOT EXISTS kpis 
                 (metric VARCHAR(50) PRIMARY KEY, threshold FLOAT)''')
    # Performance table
    c.execute('''CREATE TABLE IF NOT EXISTS performance 
                 (id INT AUTO_INCREMENT PRIMARY KEY, agent_email VARCHAR(255), 
                  attendance FLOAT, quality_score FLOAT, product_knowledge FLOAT, 
                  contact_success_rate FLOAT, onboarding FLOAT, reporting FLOAT, 
                  talk_time FLOAT, resolution_rate FLOAT, aht FLOAT, csat FLOAT, 
                  call_volume INT, date VARCHAR(50))''')
    # Insert specified users
    default_users = [
        ('tutumelchizedek8@gmail.com', 'Manager'),
        ('pammirembe@gmail.com', 'Manager'),
        ('daisynahabwe12@gmail.com', 'Agent'),
        ('tutu.melchizedek@bodabodaunion.ug', 'Agent')
    ]
    c.executemany("INSERT IGNORE INTO users (email, role) VALUES (%s, %s)", default_users)
    conn.commit()
    conn.close()


# OAuth setup
async def get_google_user(client, token):
    user_info = await client.get_userinfo(token['access_token'])
    return user_info['email']


async def authenticate_with_google():
    client = GoogleOAuth2(
        client_id=st.secrets["oauth"]["client_id"],
        client_secret=st.secrets["oauth"]["client_secret"]
    )
    # Use deployed URL if available, else fallback to localhost
    redirect_uri = st.secrets["oauth"]["redirect_uri"]
    if "STREAMLIT_CLOUD_URL" in os.environ:
        redirect_uri = f"{os.environ['STREAMLIT_CLOUD_URL']}"
    authorization_url = await client.get_authorization_url(
        redirect_uri=redirect_uri,
        scope=["email", "profile"]
    )
    return client, authorization_url


def get_db_connection():
    return mysql.connector.connect(
        host=st.secrets["mysql"]["host"],
        port=st.secrets["mysql"]["port"],
        database=st.secrets["mysql"]["database"],
        user=st.secrets["mysql"]["user"],
        password=st.secrets["mysql"]["password"]
    )


# Save KPIs
def save_kpis(kpis):
    conn = get_db_connection()
    c = conn.cursor()
    for metric, threshold in kpis.items():
        c.execute("INSERT INTO kpis (metric, threshold) VALUES (%s, %s) ON DUPLICATE KEY UPDATE threshold=%s",
                  (metric, threshold, threshold))
    conn.commit()
    conn.close()


# Get KPIs
def get_kpis():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT metric, threshold FROM kpis")
    kpis = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return kpis


# Save performance data
def save_performance(agent_email, data):
    conn = get_db_connection()
    c = conn.cursor()
    date = datetime.now().strftime("%Y-%m-%d")
    c.execute('''INSERT INTO performance 
                 (agent_email, attendance, quality_score, product_knowledge, contact_success_rate, 
                  onboarding, reporting, talk_time, resolution_rate, aht, csat, call_volume, date) 
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
              (agent_email, data['attendance'], data['quality_score'], data['product_knowledge'],
               data['contact_success_rate'], data['onboarding'], data['reporting'], data['talk_time'],
               data['resolution_rate'], data['aht'], data['csat'], data['call_volume'], date))
    conn.commit()
    conn.close()


# Get performance data
def get_performance(agent_email=None):
    conn = get_db_connection()
    query = "SELECT * FROM performance"
    if agent_email:
        query += " WHERE agent_email = %s"
        df = pd.read_sql(query, conn, params=(agent_email,))
    else:
        df = pd.read_sql(query, conn)
    conn.close()
    return df


# Assess performance based on KPIs
def assess_performance(performance_df, kpis):
    results = performance_df.copy()
    metrics = ['attendance', 'quality_score', 'product_knowledge', 'contact_success_rate',
               'onboarding', 'reporting', 'talk_time', 'resolution_rate', 'csat', 'call_volume']
    for metric in metrics:
        if metric == 'aht':
            results[f'{metric}_pass'] = results[metric] <= kpis.get(metric, 600)
        else:
            results[f'{metric}_pass'] = results[metric] >= kpis.get(metric, 50)
    results['overall_score'] = results[[f'{m}_pass' for m in metrics]].mean(axis=1) * 100
    return results


# Streamlit app
def main():
    init_db()
    st.set_page_config(page_title="Call Center Assessment System", layout="wide")

    # Session state for authentication
    if 'user' not in st.session_state:
        st.session_state.user = None
        st.session_state.role = None
        st.session_state.oauth_client = None
        st.session_state.oauth_token = None

    # OAuth login
    if not st.session_state.user:
        st.title("Login with Google")
        client, auth_url = st.runtime.get_instance().loop.run_until_complete(authenticate_with_google())
        st.session_state.oauth_client = client
        st.markdown(f"[Login with Google]({auth_url})")

        # Handle OAuth callback
        query_params = st.query_params
        if query_params:
            code = query_params.get("code")
            if code:
                try:
                    redirect_uri = st.secrets["oauth"]["redirect_uri"]
                    if "STREAMLIT_CLOUD_URL" in os.environ:
                        redirect_uri = f"{os.environ['STREAMLIT_CLOUD_URL']}"
                    token = st.runtime.get_instance().loop.run_until_complete(
                        client.get_access_token(code, redirect_uri)
                    )
                    st.session_state.oauth_token = token
                    email = st.runtime.get_instance().loop.run_until_complete(
                        get_google_user(client, token)
                    )
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT role FROM users WHERE email = %s", (email,))
                    result = c.fetchone()
                    conn.close()
                    if result:
                        st.session_state.user = email
                        st.session_state.role = result[0]
                        st.success(f"Logged in as {email} ({st.session_state.role})")
                        st.query_params.clear()
                        st.rerun()
                    else:
                        st.error("User not registered. Contact admin.")
                except Exception as e:
                    st.error(f"Login failed: {str(e)}")
        return

    # Logout button
    if st.button("Logout"):
        st.session_state.user = None
        st.session_state.role = None
        st.session_state.oauth_client = None
        st.session_state.oauth_token = None
        st.rerun()

    # Manager interface
    if st.session_state.role == "Manager":
        st.title("Manager Dashboard")
        tabs = st.tabs(["Set KPIs", "Input Performance", "View Assessments"])

        # Set KPIs
        with tabs[0]:
            st.header("Set KPI Thresholds")
            kpis = get_kpis()
            with st.form("kpi_form"):
                attendance = st.number_input("Attendance (%, min)", value=kpis.get('attendance', 95.0), min_value=0.0,
                                             max_value=100.0)
                quality_score = st.number_input("Quality Score (%, min)", value=kpis.get('quality_score', 90.0),
                                                min_value=0.0, max_value=100.0)
                product_knowledge = st.number_input("Product Knowledge (%, min)",
                                                    value=kpis.get('product_knowledge', 85.0), min_value=0.0,
                                                    max_value=100.0)
                contact_success_rate = st.number_input("Contact Success Rate (%, min)",
                                                       value=kpis.get('contact_success_rate', 80.0), min_value=0.0,
                                                       max_value=100.0)
                onboarding = st.number_input("Onboarding (%, min)", value=kpis.get('onboarding', 90.0), min_value=0.0,
                                             max_value=100.0)
                reporting = st.number_input("Reporting (%, min)", value=kpis.get('reporting', 95.0), min_value=0.0,
                                            max_value=100.0)
                talk_time = st.number_input("CRM Talk Time (seconds, min)", value=kpis.get('talk_time', 300.0),
                                            min_value=0.0)
                resolution_rate = st.number_input("Issue Resolution Rate (%, min)",
                                                  value=kpis.get('resolution_rate', 80.0), min_value=0.0,
                                                  max_value=100.0)
                aht = st.number_input("Average Handle Time (seconds, max)", value=kpis.get('aht', 600.0), min_value=0.0)
                csat = st.number_input("Customer Satisfaction (%, min)", value=kpis.get('csat', 85.0), min_value=0.0,
                                       max_value=100.0)
                call_volume = st.number_input("Call Volume (calls, min)", value=kpis.get('call_volume', 50),
                                              min_value=0)
                if st.form_submit_button("Save KPIs"):
                    new_kpis = {
                        'attendance': attendance,
                        'quality_score': quality_score,
                        'product_knowledge': product_knowledge,
                        'contact_success_rate': contact_success_rate,
                        'onboarding': onboarding,
                        'reporting': reporting,
                        'talk_time': talk_time,
                        'resolution_rate': resolution_rate,
                        'aht': aht,
                        'csat': csat,
                        'call_volume': call_volume
                    }
                    save_kpis(new_kpis)
                    st.success("KPIs saved!")

        # Input Performance
        with tabs[1]:
            st.header("Input Agent Performance")
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT email FROM users WHERE role = 'Agent'")
            agents = [row[0] for row in c.fetchall()]
            conn.close()
            with st.form("performance_form"):
                agent = st.selectbox("Select Agent", agents)
                attendance = st.number_input("Attendance (%)", min_value=0.0, max_value=100.0)
                quality_score = st.number_input("Quality Score (%)", min_value=0.0, max_value=100.0)
                product_knowledge = st.number_input("Product Knowledge (%)", min_value=0.0, max_value=100.0)
                contact_success_rate = st.number_input("Contact Success Rate (%)", min_value=0.0, max_value=100.0)
                onboarding = st.number_input("Onboarding (%)", min_value=0.0, max_value=100.0)
                reporting = st.number_input("Reporting (%)", min_value=0.0, max_value=100.0)
                talk_time = st.number_input("CRM Talk Time (seconds)", min_value=0.0)
                resolution_rate = st.number_input("Issue Resolution Rate (%)", min_value=0.0, max_value=100.0)
                aht = st.number_input("Average Handle Time (seconds)", min_value=0.0)
                csat = st.number_input("Customer Satisfaction (%)", min_value=0.0, max_value=100.0)
                call_volume = st.number_input("Call Volume (calls)", min_value=0)
                if st.form_submit_button("Submit Performance"):
                    data = {
                        'attendance': attendance,
                        'quality_score': quality_score,
                        'product_knowledge': product_knowledge,
                        'contact_success_rate': contact_success_rate,
                        'onboarding': onboarding,
                        'reporting': reporting,
                        'talk_time': talk_time,
                        'resolution_rate': resolution_rate,
                        'aht': aht,
                        'csat': csat,
                        'call_volume': call_volume
                    }
                    save_performance(agent, data)
                    st.success("Performance data saved!")

        # View Assessments
        with tabs[2]:
            st.header("Assessment Results")
            performance_df = get_performance()
            if not performance_df.empty:
                kpis = get_kpis()
                results = assess_performance(performance_df, kpis)
                st.dataframe(results)
                # Visualization
                st.subheader("Performance Overview")
                fig = px.bar(results, x='agent_email', y='overall_score', color='agent_email',
                             title="Agent Overall Scores", labels={'overall_score': 'Score (%)'})
                st.plotly_chart(fig)
            else:
                st.write("No performance data available.")

    # Agent interface
    elif st.session_state.role == "Agent":
        st.title(f"Agent Dashboard - {st.session_state.user}")
        performance_df = get_performance(st.session_state.user)
        if not performance_df.empty:
            kpis = get_kpis()
            results = assess_performance(performance_df, kpis)
            st.dataframe(results)
            # Visualization
            st.subheader("Your Performance")
            fig = px.line(results, x='date', y='overall_score', title="Your Score Over Time",
                          labels={'overall_score': 'Score (%)'})
            st.plotly_chart(fig)
        else:
            st.write("No performance data available.")


if __name__ == "__main__":
    main()