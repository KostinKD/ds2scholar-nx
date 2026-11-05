"""SotFS 360 social codecs established from this title's serializers and params.

Cell proof: sub_824708C8 + NetworkAreaParam; message proof: sub_82440A48.
Only encodes established fields; transport/import is kept separate from this module.
"""
import math
import struct


def network_grid(data: bytes, area: int) -> tuple[float, ...]:
    if len(data)<64 or not data[12:44].startswith(b'NETWORK_AREA_PARAM'):
        raise ValueError('Expected Xbox NETWORK_AREA_PARAM')
    count=struct.unpack_from('>H',data,10)[0]
    if 64+count*12>len(data):raise ValueError('Truncated param row table')
    for i in range(count):
        ident,offset,_=struct.unpack_from('>III',data,64+12*i)
        if ident!=area:continue
        if offset<64+count*12 or offset+24>len(data):raise ValueError('Invalid grid offset')
        grid=struct.unpack_from('>6f',data,offset)
        if not all(math.isfinite(x) for x in grid) or not all(x>0 for x in grid[:3]):
            raise ValueError('Invalid grid dimensions')
        return grid
    raise ValueError('Unknown online area')


def cell_id(position, grid) -> int:
    if len(position)!=3 or len(grid)!=6 or not all(math.isfinite(x) for x in (*position,*grid)):
        raise ValueError('Invalid coordinates or grid')
    if any(x<=0 for x in grid[:3]):raise ValueError('Invalid grid size')
    x,y,z=[math.floor((position[i]-grid[i+3])/grid[i]) for i in range(3)]
    if not (-512<=x<512 and -2048<=y<2048 and -512<=z<512):
        raise ValueError('Outside cell encoding range')
    return (x&1023)|((y&4095)<<10)|((z&1023)<<22)


def packed_position(position) -> bytes:
    if len(position)!=3 or not all(math.isfinite(v) for v in position):
        raise ValueError('Invalid position')
    values=[int(v*32) for v in position]  # fctiwz in sub_82698CA8 truncates toward zero.
    if any(not -32768<=v<=32767 for v in values):raise ValueError('Outside packed position range')
    return struct.pack('>3h',*values)


def message_payload(donor: bytes, position, sentence: int, word: int) -> bytes:
    if len(donor)!=24 or donor[:4] not in (b'\0\0\0\1',b'\0\0\0\2'):
        raise ValueError('Unsupported message format')
    if not isinstance(sentence,int) or not 0<=sentence<=10 or not isinstance(word,int) or not 0<=word<65535:
        raise ValueError('Invalid message selectors')
    data=bytearray(donor)
    data[4:10]=packed_position(position)
    struct.pack_into('>H',data,12,sentence)
    struct.pack_into('>H',data,16,word)
    return bytes(data)


def _replay_layout(data: bytes, kind: str):
    if kind=='ghost' and data[:4]==b'\0\x39\0\x0a':outer=16
    elif kind=='blood' and data[:4]==b'\0\x39\0\x0b':outer=4
    else:raise ValueError('Unsupported replay envelope')
    if len(data)<outer+496:raise ValueError('Truncated replay')
    version,count=struct.unpack_from('>HH',data,outer)
    start=outer+496+count*4
    if version!=57 or not 1<=count<=4096 or start>len(data):raise ValueError('Unsupported replay body')
    offsets=[];cursor=0
    for i in range(count):
        word=struct.unpack_from('>I',data,outer+496+4*i)[0]
        if (word&65535)!=cursor:raise ValueError('Inconsistent replay event offset')
        parts=(word>>16)&15
        for _ in range(parts):
            p=start+cursor
            if p+2>len(data):raise ValueError('Truncated packet header')
            header=struct.unpack_from('>H',data,p)[0];packet=header>>10;length=header&1023
            if p+2+length>len(data):raise ValueError('Truncated replay packet')
            # Proven v57 packet layouts only: poses, animation events, impact events.
            expected={0:12,1:8,7:24}
            if expected.get(packet)!=length:raise ValueError('Unverified replay packet layout')
            if packet==0:offsets.append((p+2,True))
            elif packet==7:offsets.append((p+2+8,False))
            cursor+=length+2
    if start+cursor!=len(data) or not any(pose for _,pose in offsets):
        raise ValueError('Replay has trailing bytes or no pose')
    return outer,offsets


def replay_positions(data: bytes, kind: str) -> list[tuple[float,float,float]]:
    _,offsets=_replay_layout(data,kind)
    return [tuple(v/32 for v in struct.unpack_from('>3h',data,p)) for p,pose in offsets if pose]


def translate_replay(data: bytes, kind: str, target, owner: int, sequence: int) -> bytes:
    """Shift every absolute pose/impact position; keep animation/timing/appearance.

    Body: sub_823A3168; packet traversal: sub_823A2F20/823A0D48;
    pose decoder: sub_82699030; impact packed transform: sub_824C35C8.
    """
    outer,offsets=_replay_layout(data,kind)
    if not isinstance(owner,int) or not 1<=owner<=0xffffffff or not isinstance(sequence,int) or not 0<=sequence<=0xffffffff:
        raise ValueError('Invalid synthetic owner or recording sequence')
    anchor=4 if kind=='ghost' else next(p for p,pose in offsets if pose)
    original=struct.unpack_from('>3h',data,anchor)
    destination=struct.unpack('>3h',packed_position(target))
    delta=[b-a for a,b in zip(original,destination)]
    output=bytearray(data)
    for p,_ in offsets:
        shifted=[v+delta[i] for i,v in enumerate(struct.unpack_from('>3h',data,p))]
        if any(not -32768<=v<=32767 for v in shifted):raise ValueError('Translated replay position overflows')
        struct.pack_into('>3h',output,p,*shifted)
    if kind=='ghost':
        output[4:10]=packed_position(target)
        struct.pack_into('>I',output,12,owner)
    struct.pack_into('>II',output,outer+4,owner,sequence)
    return bytes(output)
