import cv2
import numpy as np


# ============================================================
# GAUGE SETTINGSc
# ============================================================

# TEMPORARY manual gauge selection
# Later this should come from the YOLO detected class
GAUGE_TYPE = "blue"       # "white" or "blue"

# Test video settings
TEST_VIDEO = "gauge/50sec_bgauge.mp4"
TEST_TIME_MS = 10000


GAUGE_SETTINGS = {
    "white": {
        "zero_angle": 231.5,
        "gauge_range": 275.0,
        "max_pressure": 10.0
    },

    "blue": {
        "zero_angle": 222.0,
        "gauge_range": 270.0,
        "max_pressure": 10.0
    }
}


# Latest detected pressure
latest_pressure = None


def get_latest_pressure():
    return latest_pressure


# ============================================================
# WHITE GAUGE NEEDLE DETECTION
# ============================================================

def detect_white_needle(gray, gray_blurred, x, y, radius, output):

    edges = cv2.Canny(gray_blurred, 50, 150)

    # Ignore outer rim/reflections
    needle_mask = np.zeros_like(edges)

    cv2.circle(
        needle_mask,
        (x, y),
        int(radius * 0.80),
        255,
        -1
    )

    masked_edges = cv2.bitwise_and(edges, needle_mask)

    lines = cv2.HoughLinesP(
        masked_edges,
        1,
        np.pi / 180,
        threshold=50,
        minLineLength=int(radius * 0.25),
        maxLineGap=15
    )

    best_line = None
    best_distance = 0

    if lines is not None:

        for line in lines.reshape(-1, 4):

            x1, y1, x2, y2 = line

            distance1 = np.hypot(x1 - x, y1 - y)
            distance2 = np.hypot(x2 - x, y2 - y)

            near_distance = min(distance1, distance2)
            far_distance = max(distance1, distance2)

            # Needle should start near centre
            # and extend outward toward the scale
            if (
                near_distance < radius * 0.20
                and far_distance > radius * 0.45
                and far_distance < radius * 0.85
            ):

                if far_distance > best_distance:
                    best_distance = far_distance
                    best_line = (x1, y1, x2, y2)

    if best_line is None:
        print("White gauge needle not detected.")
        return None

    x1, y1, x2, y2 = best_line

    # Direction of detected needle/tail axis
    dx_line = x2 - x1
    dy_line = y2 - y1

    length = np.hypot(dx_line, dy_line)

    if length == 0:
        return None

    ux = dx_line / length
    uy = dy_line / length

    # Compare both sides of centre
    sample_distance = int(radius * 0.35)

    point_a = (
        int(x + ux * sample_distance),
        int(y + uy * sample_distance)
    )

    point_b = (
        int(x - ux * sample_distance),
        int(y - uy * sample_distance)
    )

    patch_size = 15

    def dark_pixel_count(gray_image, point):

        px, py = point

        patch = gray_image[
            max(0, py - patch_size):min(
                gray_image.shape[0],
                py + patch_size
            ),
            max(0, px - patch_size):min(
                gray_image.shape[1],
                px + patch_size
            )
        ]

        if patch.size == 0:
            return 999999

        return np.sum(patch < 100)

    dark_a = dark_pixel_count(gray, point_a)
    dark_b = dark_pixel_count(gray, point_b)

    # Thick/darker side = tail
    # Thin side = real pointer
    if dark_a < dark_b:

        tip_x = int(x + ux * radius * 0.70)
        tip_y = int(y + uy * radius * 0.70)

    else:

        tip_x = int(x - ux * radius * 0.70)
        tip_y = int(y - uy * radius * 0.70)

    # Draw detected pointer
    cv2.line(
        output,
        (x, y),
        (tip_x, tip_y),
        (255, 0, 0),
        4
    )

    cv2.circle(
        output,
        (tip_x, tip_y),
        6,
        (0, 255, 255),
        -1
    )

    # Calculate needle angle
    dx = tip_x - x
    dy = y - tip_y

    angle = np.degrees(np.arctan2(dy, dx))

    if angle < 0:
        angle += 360

    return angle


# ============================================================
# BLUE GAUGE NEEDLE DETECTION
# ============================================================

def detect_blue_needle(gray, gray_blurred, x, y, radius, output):

    edges = cv2.Canny(gray_blurred, 50, 150)

    # Ignore outer rim/reflections
    needle_mask = np.zeros_like(edges)

    cv2.circle(
        needle_mask,
        (x, y),
        int(radius * 0.80),
        255,
        -1
    )

    masked_edges = cv2.bitwise_and(edges, needle_mask)

    lines = cv2.HoughLinesP(
        masked_edges,
        1,
        np.pi / 180,
        threshold=50,
        minLineLength=int(radius * 0.25),
        maxLineGap=15
    )

    best_line = None
    best_distance = 0

    if lines is not None:

        for line in lines.reshape(-1, 4):

            x1, y1, x2, y2 = line

            distance1 = np.hypot(x1 - x, y1 - y)
            distance2 = np.hypot(x2 - x, y2 - y)

            far_distance = max(distance1, distance2)

            denominator = np.hypot(
                y2 - y1,
                x2 - x1
            )

            if denominator == 0:
                continue

            # Distance from centre to detected line
            centre_distance = abs(
                (y2 - y1) * x
                - (x2 - x1) * y
                + x2 * y1
                - y2 * x1
            ) / denominator

            if (
                centre_distance < radius * 0.10
                and far_distance > radius * 0.45
                and far_distance < radius * 0.85
            ):

                if far_distance > best_distance:
                    best_distance = far_distance
                    best_line = (x1, y1, x2, y2)

    if best_line is None:
        print("Blue gauge needle not detected.")
        return None

    x1, y1, x2, y2 = best_line

    dx_line = x2 - x1
    dy_line = y2 - y1

    length = np.hypot(dx_line, dy_line)

    if length == 0:
        return None

    ux = dx_line / length
    uy = dy_line / length

    # Compare thickness of both sides close to pivot
    def side_dark_score(gray_image, direction):

        total_score = 0

        for fraction in [
            0.22,
            0.26,
            0.30,
            0.34,
            0.38
        ]:

            px = int(
                x
                + direction
                * ux
                * radius
                * fraction
            )

            py = int(
                y
                + direction
                * uy
                * radius
                * fraction
            )

            patch_size = 8

            patch = gray_image[
                max(0, py - patch_size):min(
                    gray_image.shape[0],
                    py + patch_size
                ),
                max(0, px - patch_size):min(
                    gray_image.shape[1],
                    px + patch_size
                )
            ]

            if patch.size > 0:
                total_score += np.sum(
                    patch < 120
                )

        return total_score

    score_a = side_dark_score(gray, 1)
    score_b = side_dark_score(gray, -1)

    print(
        "Blue side thickness scores:",
        score_a,
        score_b
    )

    # Lower score = thinner side = pointer
    if score_a < score_b:

        tip_x = int(
            x + ux * radius * 0.70
        )

        tip_y = int(
            y + uy * radius * 0.70
        )

    else:

        tip_x = int(
            x - ux * radius * 0.70
        )

        tip_y = int(
            y - uy * radius * 0.70
        )

    # Draw pointer
    cv2.line(
        output,
        (x, y),
        (tip_x, tip_y),
        (255, 0, 0),
        4
    )

    cv2.circle(
        output,
        (tip_x, tip_y),
        6,
        (0, 255, 255),
        -1
    )

    # Calculate angle
    dx = tip_x - x
    dy = y - tip_y

    angle = np.degrees(
        np.arctan2(dy, dx)
    )

    if angle < 0:
        angle += 360

    return angle


# ============================================================
# PROCESS GAUGE
# ============================================================

def process_gauge(frame, gauge_type):

    global latest_pressure

    latest_pressure = None

    # STEP 3:
    # Find gauge circle and centre

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    gray_blurred = cv2.GaussianBlur(
        gray,
        (9, 9),
        2
    )

    circles = cv2.HoughCircles(
        gray_blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=200,
        param1=100,
        param2=50,
        minRadius=180,
        maxRadius=300
    )

    circle_output = frame.copy()

    if circles is None:

        print(
            "Gauge circle not detected."
        )

        return circle_output, None

    circles = np.round(
        circles[0]
    ).astype(int)

    x, y, radius = circles[0]

    print(
        "Gauge centre:",
        x,
        y
    )

    print(
        "Gauge radius:",
        radius
    )

    # Draw gauge circle
    cv2.circle(
        circle_output,
        (x, y),
        radius,
        (0, 255, 0),
        3
    )

    # Draw gauge centre
    cv2.circle(
        circle_output,
        (x, y),
        6,
        (0, 0, 255),
        -1
    )

    # STEP 4 + 5:
    # Detect needle and calculate angle

    if gauge_type == "white":

        angle = detect_white_needle(
            gray,
            gray_blurred,
            x,
            y,
            radius,
            circle_output
        )

    elif gauge_type == "blue":

        angle = detect_blue_needle(
            gray,
            gray_blurred,
            x,
            y,
            radius,
            circle_output
        )

    else:

        print(
            "Unknown gauge type."
        )

        return circle_output, None

    if angle is None:

        return circle_output, None

    print(
        f"Needle angle: "
        f"{angle:.2f} degrees"
    )

    # STEP 6:
    # Convert angle to pressure

    settings = GAUGE_SETTINGS[
        gauge_type
    ]

    zero_angle = settings[
        "zero_angle"
    ]

    gauge_range = settings[
        "gauge_range"
    ]

    max_pressure = settings[
        "max_pressure"
    ]

    angle_from_zero = (
        zero_angle - angle
    ) % 360

    if angle_from_zero > gauge_range:

        print(
            "Needle angle is outside "
            "gauge range."
        )

        return circle_output, None

    pressure = (
        angle_from_zero
        / gauge_range
    ) * max_pressure

    latest_pressure = pressure

    print(
        f"Pressure: "
        f"{pressure:.2f} bar"
    )

    # Display angle
    cv2.putText(
        circle_output,
        f"Angle: {angle:.1f} deg",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (255, 0, 0),
        2
    )

    # Display pressure
    cv2.putText(
        circle_output,
        f"Pressure: "
        f"{pressure:.2f} bar",
        (20, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (255, 0, 0),
        2
    )

    return circle_output, pressure


# ============================================================
# TEST PROGRAM
# ============================================================

if __name__ == "__main__":

    video = cv2.VideoCapture(
        TEST_VIDEO
    )

    if not video.isOpened():

        print(
            "Error: Could not open video."
        )

        exit()

    # Go to selected test timestamp
    video.set(
        cv2.CAP_PROP_POS_MSEC,
        TEST_TIME_MS
    )

    success, frame = video.read()

    if not success:

        print(
            "Error: Could not read frame."
        )

        video.release()

        exit()

    # Manually select the gauge area
    # Resize frame only for easier ROI selection
    scale = 0.3

    selection_frame = cv2.resize(
        frame,
        None,
        fx=scale,
        fy=scale
    )

    roi = cv2.selectROI(
        "Select Gauge",
        selection_frame,
        False,
        False
    )

    cv2.destroyWindow("Select Gauge")

    x, y, w, h = roi

    # Convert ROI coordinates back to original frame size
    x = int(x / scale)
    y = int(y / scale)
    w = int(w / scale)
    h = int(h / scale)

    gauge_crop = frame[y:y+h, x:x+w]

    # Save raw frame
    cv2.imwrite(
        "gauge_frame.jpg",
        frame
    )

    # Run gauge processing
    circle_output, pressure = (
        process_gauge(
            gauge_crop,
            GAUGE_TYPE
        )
    )

    if pressure is not None:

        print(
            "Returned pressure:",
            pressure
        )

    # Save processed result
    cv2.imwrite(
        "gauge_result.jpg",
        circle_output
    )

    # Resize for viewing
    display_output = cv2.resize(
        circle_output,
        None,
        fx=0.5,
        fy=0.5
    )

    cv2.imshow(
        "Gauge Result",
        display_output
    )

    cv2.waitKey(0)

    cv2.destroyAllWindows()

    video.release()
