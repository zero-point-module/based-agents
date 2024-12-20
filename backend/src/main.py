from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel
from src.services.warpcast_service import WarpcastService
from src.services.chatbot_service import ChatbotService
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.agent import AgentCreate
from src.services.database import get_db, engine
from src.services.agent_service import AgentService
import logging
import sys
import random

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Create and configure our application logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Ensure propagation to root logger
logger.propagate = True

app = FastAPI()
warpcast_service = WarpcastService()

@app.on_event("startup")
async def startup_event():
    try:
        logger.info("Starting services initialization")
        
        # Initialize Warpcast
        logger.info("Initializing Warpcast service...")
        warpcast_success = await warpcast_service.initialize()
        if not not warpcast_success:
            raise Exception("Failed to initialize Warpcast service")
        logger.info("Warpcast service initialized successfully")
            
        # Get a database session
        logger.info("Creating database session...")
        async with AsyncSession(engine) as db:
            async with db.begin():  # Start a transaction
                agent_service = AgentService(db)
                app.state.chatbot_service = ChatbotService(agent_service)
                
                logger.info("Initializing chatbot service...")
                try:
                    await app.state.chatbot_service.initialize()
                    logger.info("Chatbot service initialized successfully")
                except Exception as e:
                    logger.error(f"Error during chatbot initialization: {str(e)}", exc_info=True)
            
        logger.info("Services initialized successfully")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}", exc_info=True)  # Added exc_info for full traceback
        raise

async def get_chatbot_service(db: AsyncSession = Depends(get_db)) -> ChatbotService:
    if not hasattr(app.state, "chatbot_service"):
        async with AsyncSession(engine) as session:
            agent_service = AgentService(session)
            app.state.chatbot_service = ChatbotService(agent_service)
            await app.state.chatbot_service.initialize()
    return app.state.chatbot_service

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/warpcast/{username}")
async def get_user_casts(username: str, limit: int = 1000):
    casts = await warpcast_service.get_user_casts(username, limit)
    if "error" in casts:
        raise HTTPException(status_code=400, detail=casts["error"])
    return casts

class ChatDto(BaseModel):
    message: str
    
@app.post("/api/chat/{tag}")
async def chat(
    tag: str, 
    chat_dto: ChatDto,
    chatbot_service: ChatbotService = Depends(get_chatbot_service),
    db: AsyncSession = Depends(get_db)
):
    agent_service = AgentService(db)
    agent = await agent_service.get_agent_by_tag(tag)
    if not agent:
        raise HTTPException(status_code=400, detail="Agent with this tag does not exist")
    
    messages = [{"role": "user", "content": chat_dto.message}]
    
    # Collect all chunks into a single response
    full_response = ""
    async for chunk in chatbot_service.stream(tag, messages):
        if isinstance(chunk, str):
            full_response += chunk
    
    return {"response": full_response}

@app.post("/api/agents")
async def create_agent(
    agent: AgentCreate,
    db: AsyncSession = Depends(get_db)
):
    agent_service = AgentService(db)
    
    # Check if agent with same tag exists
    existing_agent = await agent_service.get_agent_by_tag(agent.tag)
    if existing_agent:
        raise HTTPException(status_code=400, detail="Agent with this tag already exists")
    
    casts = []
    for personality in agent.farcaster_personalities:
        casts = casts.append(await get_user_casts(personality))
    
    try:
        created_agent = await agent_service.create_agent(agent, random.shuffle(casts))
        await app.state.chatbot_service.initialize()
        return created_agent
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agents/owner/{owner_address}")
async def get_owner_agents(
    owner_address: str,
    db: AsyncSession = Depends(get_db)
):
    agent_service = AgentService(db)
    agents = await agent_service.get_agents_by_owner(owner_address)
    return agents

