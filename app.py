import streamlit as st
import pandas as pd
from datetime import datetime
import json
from io import StringIO

# --- IMPORTS FOR GOOGLE DRIVE API (Proven to work in Journal App) ---
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2 import service_account

# -----------------------
# CONFIG
# -----------------------
# --- CRITICAL VARIABLES: UPDATE THESE ---
# 1. Name of the CSV file in your Google Drive folder
SHOPPING_FILE_NAME = "shopping_list_data.csv"
# 2. The ID of the Google Drive folder where the file lives
# (Get this from the URL of your Drive folder)
FOLDER_ID = st.secrets["app_config"]["folder_id"]
# 3. The email of the user to impersonate for DWD
DELEGATED_EMAIL = st.secrets["app_config"]["delegated_email"]
# ----------------------------------------

# Define Categories and Stores
CATEGORIES = ["Vegetables", "Beverages", "Meat/Dairy", "Frozen", "Dry Goods"]
STORES = ["Costco", "Trader Joe's", "Whole Foods", "Other"] 

# -----------------------
# PAGE SETUP
# -----------------------
st.set_page_config(page_title="🛒 Shopping List", layout="centered")


# ----------------------------------------------------------------------------------
# GOOGLE DRIVE FUNCTIONS (Using googleapiclient)
# ----------------------------------------------------------------------------------

@st.cache_resource
def get_drive_service():
    """Authenticates the service account with Domain-Wide Delegation (DWD)."""
    
    # 1. Get credentials from Streamlit secrets
    creds_info = st.secrets["gcp_service_account"]
    
    # 2. Define the scope for Google Drive access
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    
    # 3. Create credentials object
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )
    
    # 4. Delegate credentials to impersonate the DELEGATED_EMAIL
    delegated_creds = creds.with_subject(DELEGATED_EMAIL)
    
    # 5. Build the Drive service client and return it
    service = build("drive", "v3", credentials=delegated_creds)
    return service

def find_file_id(service, file_name):
    """Searches for a file by name within the specified folder ID."""
    
    query = (
        f"name='{file_name}' and '{FOLDER_ID}' in parents and trashed=false"
    )
    response = service.files().list(q=query, fields="files(id)").execute()
    files = response.get("files", [])
    return files[0]["id"] if files else None

def load_data_from_drive(service):
    """Attempts to download the CSV file from Drive."""
    
    file_id = find_file_id(service, SHOPPING_FILE_NAME)
    
    if file_id is None:
        # File not found, return empty DataFrame
        default_cols = ["timestamp", "item", "purchased", "category", "store"]
        return pd.DataFrame(columns=default_cols)

    # File found, download its content
    request = service.files().get_media(fileId=file_id)
    file_content = StringIO()
    
    downloader = MediaIoBaseDownload(file_content, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        
    file_content.seek(0)
    
    try:
        df = pd.read_csv(file_content)
    except Exception:
        # Handle empty/corrupted CSV content
        default_cols = ["timestamp", "item", "purchased", "category", "store"]
        df = pd.DataFrame(columns=default_cols)
        
    return df, file_id

def save_data_to_drive(service, df, file_id=None):
    """Saves DataFrame as CSV back to Google Drive."""
    
    csv_content = df.to_csv(index=False)
    file_metadata = {"name": SHOPPING_FILE_NAME}
    
    # Convert CSV string to bytes for upload
    media_body = MediaIoBaseUpload(
        StringIO(csv_content),
        mimetype="text/csv",
        resumable=True
    )

    if file_id:
        # Update existing file
        service.files().update(
            fileId=file_id,
            media_body=media_body
        ).execute()
    else:
        # Create new file in the specified folder
        file_metadata["parents"] = [FOLDER_ID]
        file = service.files().create(
            body=file_metadata,
            media_body=media_body,
            fields="id"
        ).execute()
        return file.get("id")

# -----------------------
# DATA LOADING/SAVING WRAPPER
# -----------------------

def load_data():
    """Loads data, ensuring correct types and saving service object."""
    
    service = get_drive_service()
    df, file_id = load_data_from_drive(service)
    
    # Store service and file_id for saving in the session
    st.session_state["drive_service"] = service
    st.session_state["file_id"] = file_id
    
    # Ensure all necessary columns exist and are correct type
    default_cols = ["timestamp", "item", "purchased", "category", "store"]
    for col in default_cols:
        if col not in df.columns:
            df[col] = False if col == "purchased" else None

    if "purchased" in df.columns:
        df["purchased"] = df["purchased"].astype(bool)

    return df

def save_data(df):
    """Saves data using cached service and file_id."""
    
    service = st.session_state["drive_service"]
    file_id = st.session_state["file_id"]
    
    new_file_id = save_data_to_drive(service, df, file_id)
    
    # Update file_id if a new file was created
    if new_file_id:
        st.session_state["file_id"] = new_file_id


# -----------------------
# STYLES AND LAYOUT (Same as your previous version)
# -----------------------
st.markdown("""
<style>
h1 { font-size: 32px !important; text-align: center; }
h2 { font-size: 28px !important; text-align: center; }
p, div, label, .stMarkdown { font-size: 18px !important; line-height: 1.6; }

/* CRITICAL JS SNIPPET for faster internal rerun */
<script>
    document.addEventListener('DOMContentLoaded', () => {
        document.body.addEventListener('click', (e) => {
            if (e.target.tagName === 'A' && (e.target.href.includes('?toggle=') || e.target.href.includes('?delete='))) {
                e.preventDefault();
                history.pushState(null, '', e.target.href);
                window.location.reload(true);
            }
        });
    });
</script>

</style>
""", unsafe_allow_html=True)


# -----------------------
# APP START
# -----------------------

st.markdown(f"<h1>🛒 Shopping List</h1>", unsafe_allow_html=True)

# Load data uses the new Gdrive function
try:
    df = load_data() 
except Exception as e:
    st.error("Error connecting to Google Drive. Please check your secrets and ensure the Domain-Wide Delegation is configured correctly.")
    st.exception(e)
    st.stop()


# =====================================================
# ADD ITEM FORM (Outside of tabs so it's always visible)
# =====================================================
st.subheader("Add an Item")

# --- Store Selection ---
new_store = st.selectbox(
    "Select Store",
    STORES,
    index=None,
    placeholder="Choose a store..."
)

# --- Category Selection ---
new_category = st.selectbox(
    "Select Category", 
    CATEGORIES,
    index=None,
    placeholder="Choose a category..."
)
new_item = st.text_input("Enter the item to purchase", autocomplete="off") 

if st.button("Add Item"):
    new_item = new_item.strip()
    
    if not new_store:
        st.warning("Please select a store.")
    elif not new_category:
        st.warning("Please select a category.")
    elif not new_item:
        st.warning("Please enter a valid item name.")
    elif new_item in df["item"].values:
        st.warning("That item is already on the list.")
    else:
        # Save the new item with both category and store
        new_row = {
            "timestamp": datetime.now(), 
            "item": new_item, 
            "purchased": False, 
            "category": new_category,
            "store": new_store
        } 
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        save_data(df) # UPDATED TO SAVE VIA GOOGLE DRIVE
        st.success(f"'{new_item}' added to the list for {new_store} under '{new_category}'.")
        st.rerun()

st.markdown("---")
st.subheader("Items by Store")

# =====================================================
# STORE TABS NAVIGATION
# =====================================================

# Create the tabs dynamically
store_tabs = st.tabs(STORES)

# Loop through the store tabs to display the filtered list in each one
for store_name, store_tab in zip(STORES, store_tabs):
    with store_tab:
        
        # Filter the main DataFrame for the current store
        df_store = df[df['store'] == store_name]
        
        if df_store.empty:
            st.info(f"The list for **{store_name}** is empty. Add items above!")
            continue

        # Group and Sort Items: Group by category, then sort by purchased status within each group
        df_grouped = df_store.sort_values(by=["category", "purchased"])
        
        # Unique categories in the list
        for category, group_df in df_grouped.groupby("category"):
            # Uses the margin fix you added earlier
            st.markdown(f"**<span style='font-size: 20px; color: #1f77b4; margin-bottom: 0px !important;'>{category}</span>**", unsafe_allow_html=True)
                       
            for idx, row in group_df.iterrows():
                item_name = row["item"]
                purchased = row["purchased"]

                # 1. Determine the status emoji and style (color only)
                status_emoji = "✅" if purchased else "🛒"
                status_style = "color: #888;" if purchased else "color: #000;"
                
                # 2. Link for the status emoji (to toggle purchase)
                toggle_link = f"<a href='?toggle={idx}' target='_self' style='text-decoration: none; font-size: 18px; flex-shrink: 0; margin-right: 10px; {status_style}'>{status_emoji}</a>"
                
                # 3. Link for the delete emoji (to delete the item)
                delete_link = f"<a href='?delete={idx}' target='_self' style='text-decoration: none; font-size: 18px; flex-shrink: 0; color: #f00;'>🗑️</a>"

                # 4. Item Name display (no link)
                item_name_display = f"<span style='font-size: 14px; flex-grow: 1; {status_style}'>{item_name}</span>"

                # 5. Assemble the entire row in a single Markdown block using flexbox
                item_html = f"""
                <div style='display: flex; align-items: center; justify-content: space-between; padding: 8px 5px; margin-bottom: 3px; border-bottom: 1px solid #eee; min-height: 40px;'>
                    <div style='display: flex; align-items: center; flex-grow: 1; min-width: 1px;'>
                        {toggle_link}
                        {item_name_display}
                    </div>
                    {delete_link}
                </div>
                """
                st.markdown(item_html, unsafe_allow_html=True)
                
# ----------------------------------------------------
# FINAL CORE LOGIC BLOCK (MUST be placed at the very end of the script)
# ----------------------------------------------------
query_params = st.query_params

# Check for toggle click
toggle_id = query_params.get("toggle", None)
if toggle_id and toggle_id.isdigit():
    clicked_idx = int(toggle_id)
    if clicked_idx in df.index:
        df.loc[clicked_idx, "purchased"] = not df.loc[clicked_idx, "purchased"]
        save_data(df) # SAVING VIA GOOGLE DRIVE
        st.query_params.clear() 
        st.rerun()

# Check for delete click
delete_id = query_params.get("delete", None)
if delete_id and delete_id.isdigit():
    clicked_idx = int(delete_id)
    if clicked_idx in df.index:
        df = df.drop(clicked_idx)
        save_data(df) # SAVING VIA GOOGLE DRIVE
        st.query_params.clear() 
        st.rerun()
