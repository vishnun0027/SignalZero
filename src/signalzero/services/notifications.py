import logging
import requests
from signalzero.utils.config import settings
from typing import List, Dict, Any, TypedDict



logger = logging.getLogger("SignalZero.Notifications")

def format_discord_embed(signal_type: str, confidence: float, trigger_details: Dict[str, Any], brief: str) -> Dict[str, Any]:
    """Formats the signal notification as a beautiful Discord Embed."""
    # Determine color based on confidence (Green for high, Orange for medium)
    color = 0x2ecc71 if confidence >= 0.8 else 0xe67e22
    
    # Human-friendly title
    title_map = {
        "cross_field": "🚨 Cross-Field Citation Anomaly Detected",
        "vocab_drift": "📈 Vocabulary Emergence Monitor Shift",
        "convergent": "👥 Convergent Discovery Group Detected",
        "hn_community": "🔥 HackerNews Community Signal Detected"
    }
    title = title_map.get(signal_type, "💡 New Weak Signal Detected")
    
    fields = [
        {
            "name": "Confidence Score",
            "value": f"**{confidence * 100:.1f}%**",
            "inline": True
        }
    ]
    
    # Extract details based on type
    description = ""
    if signal_type == "cross_field":
        paper_title = trigger_details.get("title", "Unknown Title")
        arxiv_id = trigger_details.get("arxiv_id", "")
        fields.append({
            "name": "Primary Paper",
            "value": f"[{paper_title}](https://arxiv.org/abs/{arxiv_id}) (arxiv:{arxiv_id})",
            "inline": False
        })
        fields.append({
            "name": "Citing Fields",
            "value": ", ".join(trigger_details.get("citing_fields", [])),
            "inline": True
        })
        fields.append({
            "name": "Total Citations",
            "value": str(trigger_details.get("total_citations", 0)),
            "inline": True
        })
        
    elif signal_type == "vocab_drift":
        term = trigger_details.get("term", "Unknown Term")
        fields.append({
            "name": "Emergent Term",
            "value": f"`{term}`",
            "inline": False
        })
        fields.append({
            "name": "Current Freq vs. Mean",
            "value": f"{trigger_details.get('current_rel_freq', 0):.4f} (Prior Mean: {trigger_details.get('mean_prior', 0):.4f})",
            "inline": True
        })
        
    elif signal_type == "convergent":
        papers = trigger_details.get("papers", [])
        fields.append({
            "name": "Independent Papers in Cluster",
            "value": f"{len(papers)} papers",
            "inline": True
        })
        
        papers_desc = []
        for p in papers[:3]:
            papers_desc.append(f"• [{p.get('title')}](https://arxiv.org/abs/{p.get('arxiv_id')})")
        if papers_desc:
            description = "\n".join(papers_desc)

    elif signal_type == "hn_community":
        hn_title = trigger_details.get("hn_title", "Unknown HN Post")
        hn_url = trigger_details.get("hn_url", "")
        fields.append({
            "name": "HackerNews Post",
            "value": f"[{hn_title}]({hn_url})",
            "inline": False
        })
        fields.append({
            "name": "Points / Comments",
            "value": f"🔺 {trigger_details.get('points', 0)} points | 💬 {trigger_details.get('comments', 0)} comments",
            "inline": True
        })

    # Format brief into sections if it isn't empty
    if brief:
        # Check if brief contains markdown headers, else wrap in blockquotes
        formatted_brief = brief
        if len(formatted_brief) > 1024:
            formatted_brief = formatted_brief[:1020] + "..."
        fields.append({
            "name": "Why This Matters (Agent Brief)",
            "value": formatted_brief,
            "inline": False
        })
        
    embed = {
        "title": title,
        "description": description or None,
        "color": color,
        "fields": fields,
        "footer": {
            "text": "SignalZero Technology Intelligence"
        }
    }
    
    return embed

def send_discord_notification(signal_type: str, confidence: float, trigger_details: Dict[str, Any], brief: str) -> bool:
    """Sends a notification payload to the configured Discord webhook URL."""
    url = settings.DISCORD_WEBHOOK_URL
    if not url:
        logger.info("Discord webhook URL not configured. Skipping Discord notification.")
        return False
        
    embed = format_discord_embed(signal_type, confidence, trigger_details, brief)
    payload = {
        "username": "SignalZero Intelligence",
        "avatar_url": "https://raw.githubusercontent.com/google/material-design-icons/master/png/social/public/2x_web/ic_public_black_48dp.png",
        "embeds": [embed]
    }
    
    try:
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if res.status_code in [200, 204]:
            logger.info("Successfully sent notification to Discord.")
            return True
        else:
            logger.error(f"Failed to send Discord notification. Status: {res.status_code}, Response: {res.text}")
            return False
    except Exception as e:
        logger.error(f"Error posting to Discord webhook: {e}")
        return False

def send_slack_notification(signal_type: str, confidence: float, trigger_details: Dict[str, Any], brief: str) -> bool:
    """Sends a simple Slack webhook notification (if configured)."""
    url = settings.SLACK_WEBHOOK_URL
    if not url:
        return False
        
    # Slack formatting is simpler block markdown
    text_content = f"*SignalZero Alert: {signal_type.upper()} Signal Detected!*\n"
    text_content += f"*Confidence*: {confidence * 100:.1f}%\n"
    if brief:
        text_content += f"\n*Why This Matters*:\n{brief}"
        
    payload = {"text": text_content}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"Error posting to Slack webhook: {e}")
        return False

def dispatch_notifications(signal_type: str, confidence: float, trigger_details: Dict[str, Any], brief: str) -> bool:
    """Dispatches notifications to all enabled channels. Returns True if any dispatch succeeded."""
    success = False
    if settings.DISCORD_WEBHOOK_URL:
        if send_discord_notification(signal_type, confidence, trigger_details, brief):
            success = True
    if settings.SLACK_WEBHOOK_URL:
        if send_slack_notification(signal_type, confidence, trigger_details, brief):
            success = True
    return success

def send_weekly_digest_discord(signals: List[Any]) -> bool:
    """Sends a summary of multiple signals as a multi-embed message to Discord."""
    url = settings.DISCORD_WEBHOOK_URL
    if not url:
        return False
        
    import json
    embeds = []
    
    # 1. Main Header Embed
    header_embed = {
        "title": "📊 SignalZero Weekly Digest",
        "description": f"Here is the summary of the top **{len(signals)}** emerging technology signals detected over the last 7 days.",
        "color": 0x3498db,
        "footer": {
            "text": "SignalZero Headless Intelligence"
        }
    }
    embeds.append(header_embed)
    
    # 2. Embed for each signal
    for idx, signal in enumerate(signals, 1):
        try:
            details = json.loads(str(signal.trigger_details))
        except Exception:
            details = signal.trigger_details
            
        color = 0x2ecc71 if signal.confidence >= 0.8 else 0xe67e22
        
        title_map = {
            "cross_field": "Cross-Field Citation Anomaly",
            "vocab_drift": "Vocabulary Emergence Monitor",
            "convergent": "Convergent Discovery Group",
            "hn_community": "HackerNews Community Signal"
        }
        type_title = title_map.get(signal.type, "Emerging Signal")
        
        description_parts = []
        if signal.type == "cross_field":
            paper_title = details.get("title", "Unknown Title")
            arxiv_id = details.get("arxiv_id", "")
            description_parts.append(f"**Primary Paper:** [{paper_title}](https://arxiv.org/abs/{arxiv_id})")
            description_parts.append(f"**Citing Fields:** {', '.join(details.get('citing_fields', []))}")
        elif signal.type == "vocab_drift":
            term = details.get("term", "Unknown Term")
            description_parts.append(f"**Emergent Term:** `{term}`")
        elif signal.type == "convergent":
            papers = details.get("papers", [])
            description_parts.append(f"**Cluster Size:** {len(papers)} independent papers")
        elif signal.type == "hn_community":
            hn_title = details.get("hn_title", "Unknown HN Post")
            hn_url = details.get("hn_url", "")
            description_parts.append(f"**HackerNews Post:** [{hn_title}]({hn_url})")
            description_parts.append(f"**Points / Comments:** 🔺 {details.get('points', 0)} points | 💬 {details.get('comments', 0)} comments")
            
        if signal.brief:
            brief_text = signal.brief
            if len(brief_text) > 400:
                brief_text = brief_text[:397] + "..."
            description_parts.append(f"\n*Agent Brief:*\n{brief_text}")
            
        embeds.append({
            "title": f"#{idx}: {type_title} (Confidence: {signal.confidence * 100:.1f}%)",
            "description": "\n".join(description_parts),
            "color": color
        })
        
    payload = {
        "username": "SignalZero Weekly Digest",
        "avatar_url": "https://raw.githubusercontent.com/google/material-design-icons/master/png/social/public/2x_web/ic_public_black_48dp.png",
        "embeds": embeds
    }
    
    try:
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        if res.status_code in [200, 204]:
            logger.info("Successfully sent weekly digest to Discord.")
            return True
        else:
            logger.error(f"Failed to send Discord weekly digest. Status: {res.status_code}, Response: {res.text}")
            return False
    except Exception as e:
        logger.error(f"Error posting Discord weekly digest: {e}")
        return False

def send_weekly_digest_slack(signals: List[Any]) -> bool:
    """Sends a summary of multiple signals as structured Block Kit markdown to Slack."""
    url = settings.SLACK_WEBHOOK_URL
    if not url:
        return False
        
    import json
    
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📊 SignalZero Weekly Digest"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Here is the summary of the top *{len(signals)}* emerging technology signals detected over the last 7 days."
            }
        },
        {"type": "divider"}
    ]
    
    for idx, signal in enumerate(signals, 1):
        try:
            details = json.loads(str(signal.trigger_details))
        except Exception:
            details = signal.trigger_details
            
        title_map = {
            "cross_field": "Cross-Field Citation Anomaly",
            "vocab_drift": "Vocabulary Emergence Monitor",
            "convergent": "Convergent Discovery Group",
            "hn_community": "HackerNews Community Signal"
        }
        type_title = title_map.get(signal.type, "Emerging Signal")
        
        detail_lines = []
        if signal.type == "cross_field":
            paper_title = details.get("title", "Unknown Title")
            arxiv_id = details.get("arxiv_id", "")
            detail_lines.append(f"*Primary Paper:* <https://arxiv.org/abs/{arxiv_id}|{paper_title}>")
            detail_lines.append(f"*Citing Fields:* {', '.join(details.get('citing_fields', []))}")
        elif signal.type == "vocab_drift":
            term = details.get("term", "Unknown Term")
            detail_lines.append(f"*Emergent Term:* `{term}`")
        elif signal.type == "convergent":
            papers = details.get("papers", [])
            detail_lines.append(f"*Cluster Size:* {len(papers)} independent papers")
        elif signal.type == "hn_community":
            hn_title = details.get("hn_title", "Unknown HN Post")
            hn_url = details.get("hn_url", "")
            detail_lines.append(f"*HackerNews Post:* <{hn_url}|{hn_title}>")
            detail_lines.append(f"*Points / Comments:* 🔺 {details.get('points', 0)} | 💬 {details.get('comments', 0)}")
            
        brief_text = signal.brief or ""
        if len(brief_text) > 400:
            brief_text = brief_text[:397] + "..."
            
        block_text = f"*{idx}. {type_title}* (Confidence: {signal.confidence * 100:.1f}%)\n"
        block_text += "\n".join(detail_lines)
        if brief_text:
            block_text += f"\n_Agent Brief:_\n{brief_text}"
            
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": block_text
            }
        })
        blocks.append({"type": "divider"})
        
    payload = {"blocks": blocks}
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            logger.info("Successfully sent weekly digest to Slack.")
            return True
        else:
            logger.error(f"Failed to send Slack weekly digest. Status: {res.status_code}, Response: {res.text}")
            return False
    except Exception as e:
        logger.error(f"Error posting Slack weekly digest: {e}")
        return False

def compile_and_send_weekly_digest(db) -> bool:
    """Retrieves top 5 signals from the last 7 days, ranks them by confidence,
    and sends a weekly summary digest to Discord and/or Slack.
    """
    import datetime
    from signalzero.models.models import Signal
    
    # Fetch signals from the last 7 days with high/medium confidence
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    signals = db.query(Signal).filter(
        Signal.created_at >= cutoff,
        Signal.status.in_(["emerging", "growing"])
    ).order_by(Signal.confidence.desc()).limit(5).all()
    
    if not signals:
        logger.info("No active emerging or growing signals found in the last 7 days. Skipping weekly digest.")
        return False
        
    logger.info(f"Compiling weekly digest for {len(signals)} signals...")
    
    discord_success = False
    if settings.DISCORD_WEBHOOK_URL:
        discord_success = send_weekly_digest_discord(signals)
        
    slack_success = False
    if settings.SLACK_WEBHOOK_URL:
        slack_success = send_weekly_digest_slack(signals)
        
    return discord_success or slack_success
