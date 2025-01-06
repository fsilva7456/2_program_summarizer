import os
import logging
from contextlib import asynccontextmanager
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up application...")
    logger.info("Checking environment variables...")
    if not all([os.getenv('OPENAI_API_KEY'), os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY')]):
        logger.error("Missing required environment variables!")
    else:
        logger.info("All required environment variables are set")
    yield
    # Shutdown
    logger.info("Shutting down application...")

# Initialize FastAPI with lifespan
app = FastAPI(lifespan=lifespan)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Supabase client
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

class CompetitorResponse(BaseModel):
    id: int
    competitor_name: str
    program_summary: Optional[str]

def get_loyalty_program_summary(competitor_name: str) -> str:
    """
    Use OpenAI to generate a summary of the competitor's loyalty program
    """
    logger.info(f"Generating loyalty program summary for {competitor_name}")
    prompt = f"""Research and provide a concise summary of {competitor_name}'s loyalty program.
    Focus on key features like:
    - Program name
    - How points are earned
    - Main benefits and rewards
    - Special features
    
    Provide this with 3 key bullet points and then a single, well-formatted paragraph."""
    
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that researches loyalty programs."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.choices[0].message.content.strip()

def update_competitor_summary(competitor_id: int, competitor_name: str) -> CompetitorResponse:
    """
    Update a competitor's row with their loyalty program summary
    """
    logger.info(f"Updating summary for competitor ID {competitor_id}: {competitor_name}")
    summary = get_loyalty_program_summary(competitor_name)
    
    response = supabase.table('competitors').update({
        'program_summary': summary
    }).eq('id', competitor_id).execute()
    
    updated_competitor = response.data[0]
    logger.info(f"Successfully updated summary for {competitor_name}")
    
    return CompetitorResponse(**updated_competitor)

@app.get("/")
async def root():
    logger.info("Health check endpoint called")
    return {"status": "API is running"}

@app.post("/update-single/{competitor_id}")
async def update_single_competitor(competitor_id: int):
    """
    Update the loyalty program summary for a single competitor
    """
    try:
        logger.info(f"Received request to update competitor ID: {competitor_id}")
        
        # Get competitor details
        response = supabase.table('competitors').select('*').eq('id', competitor_id).execute()
        
        if not response.data:
            logger.error(f"No competitor found with ID {competitor_id}")
            raise HTTPException(status_code=404, detail="Competitor not found")
            
        competitor = response.data[0]
        updated_competitor = update_competitor_summary(competitor_id, competitor['competitor_name'])
        
        return updated_competitor
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-all")
async def update_all_competitors():
    """
    Update loyalty program summaries for all competitors without summaries
    """
    try:
        logger.info("Starting batch update of all competitors")
        response = supabase.table('competitors').select('id, competitor_name').is_('program_summary', 'null').execute()
        
        if not response.data:
            logger.info("No competitors found needing summary updates")
            return {"status": "No competitors found needing updates"}
        
        logger.info(f"Found {len(response.data)} competitors to process")
        updated_competitors = []
        
        for competitor in response.data:
            try:
                updated = update_competitor_summary(competitor['id'], competitor['competitor_name'])
                updated_competitors.append(updated)
                logger.info(f"Successfully processed {competitor['competitor_name']}")
            except Exception as e:
                logger.error(f"Error processing {competitor['competitor_name']}: {str(e)}")
        
        return {
            "status": "success",
            "total_processed": len(updated_competitors),
            "updated_competitors": updated_competitors
        }
        
    except Exception as e:
        logger.error(f"Error in batch update: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
