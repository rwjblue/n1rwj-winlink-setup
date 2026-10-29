// This file is overlaid into the pinned Pat app package by build_pat.py.
package app

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"time"
)

func stationAfterQSY(hz int) error {
	hook := os.Getenv("PAT_STATION_QSY_HOOK")
	if hook == "" {
		return nil
	}
	// This runs after Hamlib's short TCP transaction has finished. Band recall
	// and stable native DATA-A/filter readback can take several seconds.
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, hook, strconv.Itoa(hz))
	cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("station DATA-A setup after QSY: %w", err)
	}
	return nil
}
