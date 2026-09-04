import express from 'express';
import { AccessToken, RoomServiceClient } from 'livekit-server-sdk';
import dotenv from 'dotenv';

dotenv.config();

const required = ['LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET', 'LIVEKIT_HOST'];
const missing = required.filter((name) => !process.env[name]);
if (missing.length) {
  throw new Error(`Missing required environment variables: ${missing.join(', ')}`);
}

const app = express();
app.use(express.json({ limit: '32kb' }));

const apiKey = process.env.LIVEKIT_API_KEY;
const apiSecret = process.env.LIVEKIT_API_SECRET;
const livekitHost = process.env.LIVEKIT_HOST;
const roomService = new RoomServiceClient(livekitHost, apiKey, apiSecret);

const jsonError = (res, status, message) => res.status(status).json({ success: false, error: message });

app.post('/api/v1/livekit/token', async (req, res) => {
  try {
    const { roomName, identity, userName, isInstructor = false } = req.body;
    if (typeof roomName !== 'string' || !roomName.trim() || typeof identity !== 'string' || !identity.trim()) {
      return jsonError(res, 400, 'roomName and identity are required.');
    }

    const token = new AccessToken(apiKey, apiSecret, {
      identity,
      name: userName || identity,
      ttl: '2h',
    });
    token.addGrant({
      room: roomName,
      roomJoin: true,
      canPublish: Boolean(isInstructor),
      canSubscribe: true,
      canPublishData: true,
      roomAdmin: Boolean(isInstructor),
      roomMute: Boolean(isInstructor),
    });

    return res.status(200).json({
      success: true,
      data: { token: await token.toJwt(), ws_url: livekitHost, room: roomName, identity },
    });
  } catch (error) {
    console.error('Error generating token:', error);
    return jsonError(res, 500, 'Unable to generate LiveKit token.');
  }
});

app.post('/api/v1/livekit/rooms', async (req, res) => {
  try {
    const { roomName, emptyTimeout = 300, maxParticipants = 200 } = req.body;
    if (typeof roomName !== 'string' || !roomName.trim()) return jsonError(res, 400, 'roomName is required.');
    if (!Number.isInteger(emptyTimeout) || emptyTimeout < 0 || !Number.isInteger(maxParticipants) || maxParticipants < 1) {
      return jsonError(res, 400, 'emptyTimeout and maxParticipants must be valid positive integers.');
    }
    const room = await roomService.createRoom({ name: roomName, emptyTimeout, maxParticipants });
    return res.status(201).json({ success: true, data: room });
  } catch (error) {
    console.error('Error creating room:', error);
    return jsonError(res, 502, 'Unable to create LiveKit room.');
  }
});

app.post('/api/v1/livekit/rooms/mute-participant', async (req, res) => {
  try {
    const { roomName, identity, trackSid, mute = true } = req.body;
    if (!roomName || !identity || !trackSid || typeof mute !== 'boolean') return jsonError(res, 400, 'roomName, identity, trackSid, and boolean mute are required.');
    await roomService.mutePublishedTrack(roomName, identity, trackSid, mute);
    return res.status(200).json({ success: true, message: `Participant ${identity} track state updated (muted: ${mute}).` });
  } catch (error) {
    console.error('Error muting track:', error);
    return jsonError(res, 502, 'Unable to update participant track.');
  }
});

app.delete('/api/v1/livekit/rooms/:roomName', async (req, res) => {
  try {
    await roomService.deleteRoom(req.params.roomName);
    return res.status(200).json({ success: true, message: `Room ${req.params.roomName} successfully closed.` });
  } catch (error) {
    console.error('Error deleting room:', error);
    return jsonError(res, 502, 'Unable to close LiveKit room.');
  }
});

app.use((error, _req, res, _next) => {
  if (error instanceof SyntaxError && error.status === 400 && 'body' in error) return jsonError(res, 400, 'Request body must be valid JSON.');
  return jsonError(res, 500, 'Unexpected server error.');
});

const port = Number(process.env.PORT || 5100);
app.listen(port, () => console.log(`LiveKit API service running on port ${port}`));
