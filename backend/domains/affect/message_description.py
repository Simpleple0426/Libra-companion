"""Descriptions of received messages, separate from response instructions."""
import json
import math


def user_message_description(content, message_type='text', *, voice_emotion=None):
    text = str(content or '')
    if message_type == 'voice':
        description = '用户发来一条语音'
        if text.strip():
            description += '，内容：' + text
        if isinstance(voice_emotion, dict):
            label = voice_emotion.get('emotion')
            confidence = voice_emotion.get('confidence')
            if (isinstance(label, str) and label.strip()
                    and type(confidence) in (int, float)
                    and math.isfinite(confidence) and 0 < confidence <= 1):
                description += '；语音情绪识别：' + label.strip()
        return description
    if message_type == 'sticker':
        # The upload endpoint records the name and catalog meaning together.
        return text if text.startswith('用户发来一个表情包') else '用户发来一个表情包'
    if message_type == 'image':
        caption = text.strip()
        return '用户发来一张图片' + ('，配文：' + text if caption and caption != '[图片]' else '')
    if message_type == 'xhs_card':
        try:
            card = json.loads(text)
        except (ValueError, TypeError):
            card = {}
        comment = card.get('comment') if isinstance(card, dict) else None
        return '用户分享了一篇小红书' + (
            '，配文：' + comment if isinstance(comment, str) and comment.strip() else '')
    return '用户发来一条消息：' + text
