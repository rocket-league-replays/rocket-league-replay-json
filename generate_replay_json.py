import json
import pickle
import sys
from pprint import pprint

from pyrope import Replay


class Generator(object):

    actor_metadata = {}
    goal_metadata = {}
    match_metadata = {}
    actors = {}
    frame_data = []

    def __init__(self, file_path=None):
        if not file_path:
            file_path = sys.argv[1]

        print(file_path)

        try:
            self.replay = pickle.load(open(file_path + '.pickle', "rb"))
            self.replay_id = self.replay.header['Id']
        except:
            self.replay = Replay(path=file_path)
            self.replay_id = self.replay.header['Id']
            self.replay.parse_netstream()

            pickle.dump(self.replay, open(file_path + '.pickle', 'wb'))

        # Extract the goal information.
        if 'Goals' in self.replay.header:
            for goal in self.replay.header['Goals']:
                self.extract_goal_data(goal['frame'])

        self.get_match_metadata()
        self.get_actors()

        for player in self.actors:
            # Get their position data.
            self.actors[player]['position_data'] = self.get_player_position_data(player)

        # Restructure the data so that it's chunkable.
        frame_data = []

        for frame in range(self.replay.header['NumFrames']):
            frame_dict = {
                'time': self.replay.netstream[frame].current,
                'actors': []
            }

            for player in self.actors:
                position_data = self.actors[player]['position_data']

                if frame in position_data:
                    frame_dict['actors'].append({
                        'id': player,
                        'type': 'car',
                        **position_data[frame]
                    })

            frame_data.append(frame_dict)

        assert len(frame_data) == self.replay.header['NumFrames'], "Missing {} frames from data output.".format(
            self.replay.header['NumFrames'] - len(frame_data)
        )

        self.frame_data = frame_data

        pprint(self.goal_metadata)
        pprint(self.actor_metadata)

        # exit()

        # json.dump(frame_data, open(file_path + '.json', 'w'), indent=2)

    def get_match_metadata(self):
        # Search through the frames looking for some game replication info.
        for index, frame in self.replay.netstream.items():
            game_info = [
                value for name, value in frame.actors.items()
                if (
                    'GameReplicationInfoArchetype' in name and
                    'Engine.GameReplicationInfo:ServerName' in value['data']
                )
            ]

            if not game_info:
                continue

            game_info = game_info[0]['data']

            self.match_metadata = {
                'server_name': game_info['Engine.GameReplicationInfo:ServerName'],
                'playlist': game_info['ProjectX.GRI_X:ReplicatedGamePlaylist']
            }

            break

    def extract_goal_data(self, base_index, search_index=None):
        if not search_index:
            search_index = base_index

        frame = self.replay.netstream[search_index]

        scorer = None

        pri_ta = [value for name, value in frame.actors.items() if 'e_Default__PRI_TA' in name]

        # Figure out who scored.
        for value in pri_ta:
            if 'TAGame.PRI_TA:MatchGoals' in value['data']:
                scorer = value['actor_id']
                break

        if not scorer:
            self.extract_goal_data(base_index, search_index - 1)
            return

        self.goal_metadata[base_index] = scorer

    def get_actors(self):
        for index, frame in self.replay.netstream.items():
            # Find the player actor objects.
            pri_ta = [value for name, value in frame.actors.items() if 'e_Default__PRI_TA' in name]

            for value in pri_ta:
                """
                Example `value`:

                {'actor_id': 2,
                 'actor_type': 'TAGame.Default__PRI_TA',
                 'data': {'Engine.PlayerReplicationInfo:Ping': 24,
                          'Engine.PlayerReplicationInfo:PlayerID': 656,
                          'Engine.PlayerReplicationInfo:PlayerName': "AvD Sub'n",
                          'Engine.PlayerReplicationInfo:Team': (True, 6),
                          'Engine.PlayerReplicationInfo:UniqueId': (1, 76561198040631598, 0),
                          'Engine.PlayerReplicationInfo:bReadyToPlay': True,
                          'TAGame.PRI_TA:CameraSettings': {'dist': 270.0,
                                                           'fov': 107.0,
                                                           'height': 110.0,
                                                           'pitch': -2.0,
                                                           'stiff': 1.0,
                                                           'swiv': 4.300000190734863},
                          'TAGame.PRI_TA:ClientLoadout': (11, [23, 0, 613, 39, 752, 0, 0]),
                          'TAGame.PRI_TA:ClientLoadoutOnline': (11, 0, 0),
                          'TAGame.PRI_TA:PartyLeader': (1, 76561198071203042, 0),
                          'TAGame.PRI_TA:ReplicatedGameEvent': (True, 1),
                          'TAGame.PRI_TA:Title': 0,
                          'TAGame.PRI_TA:TotalXP': 9341290,
                          'TAGame.PRI_TA:bUsingSecondaryCamera': True},
                 'new': False,
                 'startpos': 102988}
                 """

                if 'Engine.PlayerReplicationInfo:PlayerName' not in value['data']:
                    continue

                team_id = None
                actor_id = value['actor_id']

                if 'Engine.PlayerReplicationInfo:Team' in value['data']:
                    team_id = value['data']['Engine.PlayerReplicationInfo:Team'][1]

                if actor_id in self.actors:
                    if (not self.actors[actor_id]['team'] and team_id) or team_id == -1:
                        self.actors[actor_id]['team'] = team_id

                elif 'TAGame.PRI_TA:ClientLoadout' in value['data']:
                    player_name = value['data']['Engine.PlayerReplicationInfo:PlayerName']

                    self.actors[actor_id] = {
                        'join': index,
                        'left': self.replay.header['NumFrames'],
                        'name': player_name,
                        'team': team_id,
                    }

                    if actor_id not in self.actor_metadata:
                        self.actor_metadata[actor_id] = value['data']

    def get_player_position_data(self, player_id):
        player = self.actors[player_id]
        result = {}

        car_actor_obj = None

        for index in range(player['join'], player['left']):
            try:
                frame = self.replay.netstream[index]
            except KeyError:
                # Handle truncated network data.
                break

            # First we need to find the player's car object.
            for actor in frame.actors:
                actor_obj = frame.actors[actor]

                if 'data' not in actor_obj:
                    continue

                engine = actor_obj['data'].get('Engine.Pawn:PlayerReplicationInfo')

                # This is the correct object for this player.
                if engine and engine[1] == player_id:
                    car_actor_obj = actor_obj['actor_id']

                # If the actor we're looking at is the car object, then get the
                # position and rotation data for this frame.
                if actor_obj['actor_id'] == car_actor_obj:
                    state_data = actor_obj['data'].get('TAGame.RBActor_TA:ReplicatedRBState')

                    if state_data:
                        x, y, z = state_data['pos']
                        yaw, pitch, roll = state_data['rot']

                        result[index] = {
                            'x': x,
                            'y': y,
                            'z': z,
                            'pitch': pitch,
                            'roll': roll,
                            'yaw': yaw
                        }

        return result


if __name__ == '__main__':
    for replay_file in sys.argv[1:]:
        Generator(replay_file)
