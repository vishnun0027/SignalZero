import logging
from src.config import settings
from src.notifications import dispatch_notifications

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TestDiscord")

def main():
    print("\n" + "="*50)
    print("SignalZero Discord Webhook Tester")
    print("="*50 + "\n")
    
    if not settings.DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL is not set in your .env file!")
        return
        
    mock_trigger = {
        "arxiv_id": "1706.03762",
        "title": "Attention Is All You Need",
        "field_spread": 4,
        "citing_fields": ["cs.CL", "cs.CV", "cs.SD", "q-bio"],
        "total_citations": 45,
        "published_date": "2017-06-12"
    }
    
    mock_brief = """**Core Novelty:**
Introduces the Transformer architecture, replacing recurrent layers entirely with self-attention mechanisms to allow parallel training and capture long-range dependencies.

**Why It Matters:**
* **Cross-Domain Utility:** Rapidly adopted beyond NLP (computational linguistics) into Computer Vision (ViTs), Audio Processing, and Biology.
* **Velocity:** Citation velocity is accelerating dramatically within the first 6 months.

**Watch List:**
* Watch for vision transformer publications, multimodal frameworks, and protein-folding adaptations."""
    
    logger.info("Sending mock signal notification to Discord...")
    success = dispatch_notifications(
        signal_type="cross_field",
        confidence=0.84,
        trigger_details=mock_trigger,
        brief=mock_brief
    )
    
    print("\n" + "="*50)
    if success:
        print("SUCCESS: Mock notification dispatched! Check your Discord channel.")
    else:
        print("FAILED: Check the logs above. Ensure your Discord webhook URL is valid.")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
