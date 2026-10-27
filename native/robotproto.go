// Robot-protocol frames carried by DP15 (Tuya laser-robot protocol).
// V1 framing (what this firmware accepts): AA 01 00000000 <len32BE> <payload> <cksum>
// payload includes the command byte; cksum = sum(payload) & 0xFF.
package main

import "fmt"

func robotFrameV1(payload []byte) []byte {
	frame := make([]byte, 0, 6+len(payload)+1)
	frame = append(frame, 0xAA, 0x01, 0x00, 0x00, 0x00, byte(len(payload)))
	frame = append(frame, payload...)
	sum := 0
	for _, b := range payload {
		sum += int(b)
	}
	return append(frame, byte(sum&0xFF))
}

// roomCleanFrame builds the 0x14 room-clean command (verified live on this robot:
// aa01000000041401010117 = 1 pass, room 1).
func roomCleanFrame(passes int, roomIDs []int) []byte {
	payload := []byte{0x14, byte(passes), byte(len(roomIDs))}
	for _, id := range roomIDs {
		payload = append(payload, byte(id))
	}
	return robotFrameV1(payload)
}

// requestFrame builds a bare request frame (e.g. cmd 0x13 virtual-wall list).
func requestFrame(cmd byte) []byte {
	return robotFrameV1([]byte{cmd})
}

var _ = fmt.Sprintf
